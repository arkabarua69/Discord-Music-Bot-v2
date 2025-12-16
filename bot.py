# --------------------
import os
import random
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View
import yt_dlp
from dotenv import load_dotenv

# --------------------
# Load environment
# --------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
FFMPEG_PATH = "ffmpeg" if os.name != "nt" else "ffmpeg.exe"

# --------------------
# Intents
# --------------------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# --------------------
# YTDL setup
# --------------------
ytdl_opts = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "extract_flat": False,
    "default_search": "ytsearch",
    "cookies": "cookies.txt",   # 🔥 THIS LINE FIXES THE ERROR
    "source_address": "0.0.0.0"
}

ytdl = yt_dlp.YoutubeDL(ytdl_opts)


# --------------------
# Music State
# --------------------
class MusicState:
    def __init__(self):
        self.queue = []
        self.current = None
        self.loop = False
        self.autoplay = False
        self.volume = 1.0
        self.previous = None


music_states = {}  # guild_id -> MusicState


# --------------------
# Music Control View
# --------------------
class MusicControlView(View):
    def __init__(self, vc: discord.VoiceClient, guild_id: int):
        super().__init__(timeout=None)
        self.vc = vc
        self.guild_id = guild_id

    def _check_user(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.user.voice is None
            or interaction.user.voice.channel != self.vc.channel
        ):
            asyncio.create_task(
                interaction.response.send_message(
                    "❌ You must be in the same voice channel!", ephemeral=True
                )
            )
            return False
        return True

    @discord.ui.button(label="🔉 Down", style=discord.ButtonStyle.secondary)
    async def volume_down(self, interaction, button):
        if not self._check_user(interaction):
            return
        state = music_states[self.guild_id]
        state.volume = max(0.1, state.volume - 0.1)
        self.vc.source.volume = state.volume
        await interaction.response.send_message(
            f"🔉 Volume: {int(state.volume*100)}%", ephemeral=True
        )

    @discord.ui.button(label="🔊 Up", style=discord.ButtonStyle.secondary)
    async def volume_up(self, interaction, button):
        if not self._check_user(interaction):
            return
        state = music_states[self.guild_id]
        state.volume = min(2.0, state.volume + 0.1)
        self.vc.source.volume = state.volume
        await interaction.response.send_message(
            f"🔊 Volume: {int(state.volume*100)}%", ephemeral=True
        )

    @discord.ui.button(label="⏮ Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button):
        if not self._check_user(interaction):
            return
        state = music_states[self.guild_id]
        if state.previous:
            state.queue.insert(0, state.current)
            state.current = state.previous
            self.vc.stop()
            await interaction.response.send_message(
                "⏮ Playing previous track", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ No previous track", ephemeral=True
            )

    @discord.ui.button(label="⏸ Pause/▶ Resume", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction, button):
        if not self._check_user(interaction):
            return
        if self.vc.is_playing():
            self.vc.pause()
            await interaction.response.send_message("⏸ Paused", ephemeral=True)
        elif self.vc.is_paused():
            self.vc.resume()
            await interaction.response.send_message("▶ Resumed", ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Nothing playing", ephemeral=True
            )

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction, button):
        if not self._check_user(interaction):
            return
        self.vc.stop()
        await interaction.response.send_message("⏭ Skipped", ephemeral=True)

    @discord.ui.button(label="🔀 Shuffle", style=discord.ButtonStyle.secondary)
    async def shuffle(self, interaction, button):
        if not self._check_user(interaction):
            return
        state = music_states[self.guild_id]
        random.shuffle(state.queue)
        await interaction.response.send_message("🔀 Queue shuffled", ephemeral=True)

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction, button):
        if not self._check_user(interaction):
            return
        state = music_states[self.guild_id]
        state.loop = not state.loop
        await interaction.response.send_message(
            f"🔁 Loop {'enabled' if state.loop else 'disabled'}", ephemeral=True
        )

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction, button):
        if not self._check_user(interaction):
            return
        self.vc.stop()
        await self.vc.disconnect()
        music_states.pop(self.guild_id, None)
        await interaction.response.edit_message(
            content="⏹️ Stopped and left the channel", embed=None, view=None
        )

    @discord.ui.button(label="🔄 AutoPlay", style=discord.ButtonStyle.primary)
    async def autoplay(self, interaction, button):
        if not self._check_user(interaction):
            return
        state = music_states[self.guild_id]
        state.autoplay = not state.autoplay
        await interaction.response.send_message(
            f"🔄 AutoPlay {'enabled' if state.autoplay else 'disabled'}", ephemeral=True
        )

    @discord.ui.button(label="📃 Playlist", style=discord.ButtonStyle.primary)
    async def playlist(self, interaction, button):
        if not self._check_user(interaction):
            return
        state = music_states[self.guild_id]
        if not state.queue:
            await interaction.response.send_message("📃 Queue is empty", ephemeral=True)
        else:
            qlist = "\n".join(
                [f"{i+1}. {t['title']}" for i, t in enumerate(state.queue)]
            )
            await interaction.response.send_message(
                f"📃 Playlist:\n{qlist}", ephemeral=True
            )


# --------------------
# Play next track
# --------------------
def play_next(vc: discord.VoiceClient, guild_id: int):
    state = music_states.get(guild_id)
    if not state:
        return

    if state.loop and state.current:
        track = state.current
    elif state.queue:
        state.previous = state.current
        track = state.queue.pop(0)
        state.current = track
    elif state.autoplay and state.current:
        # Autoplay: pick a random related song
        try:
            query = state.current["title"]
            info = ytdl.extract_info(f"ytsearch:{query}", download=False)[
                "entries"][0]
            track = {
                "title": info["title"],
                "url": info["url"] if "url" in info else info["formats"][0]["url"],
                "webpage": info.get("webpage_url", "https://youtube.com"),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", "Unknown"),
                "requester": interaction.user,
            }

            state.current = track
        except:
            track = None
    else:
        track = None

    if track:
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(
                track["url"],
                executable=FFMPEG_PATH,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            )
        )
        source.volume = state.volume
        # Schedule the next track safely in the main loop
        vc.play(
            source,
            after=lambda e: asyncio.run_coroutine_threadsafe(
                _play_next_async(vc, guild_id), bot.loop
            ),
        )
    else:
        # Queue ended → remove music panel and disconnect
        asyncio.run_coroutine_threadsafe(_end_music(vc, guild_id), bot.loop)


async def _play_next_async(vc: discord.VoiceClient, guild_id: int):
    play_next(vc, guild_id)


async def _end_music(vc: discord.VoiceClient, guild_id: int):
    try:
        # Remove music panel if it exists
        if vc.is_connected():
            for message in getattr(vc, "music_messages", []):
                try:
                    await message.delete()
                except:
                    pass

            await vc.disconnect()
        music_states.pop(guild_id, None)
        # Optional: send a small message in the text channel
        text_channel = getattr(vc, "text_channel", None)
        if text_channel:
            await text_channel.send("⏹️ Queue ended. Bot has left the voice channel.")
    except:
        pass


# --------------------
# /play command
# --------------------
@tree.command(name="play", description="Play a song from YouTube")
@app_commands.describe(query="Song name or YouTube link")
async def play(interaction: discord.Interaction, query: str):
    if not interaction.user.voice:
        await interaction.response.send_message(
            "❌ Join a voice channel first!", ephemeral=True
        )
        return

    await interaction.response.defer()
    channel = interaction.user.voice.channel
    vc = interaction.guild.voice_client
    if not vc:
        vc = await channel.connect()
    elif vc.channel != channel:
        await vc.move_to(channel)

    guild_id = interaction.guild.id
    if guild_id not in music_states:
        music_states[guild_id] = MusicState()
    state = music_states[guild_id]

    try:
        info = ytdl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]

        track = {
            "title": info["title"],
            "url": info["url"],
            "webpage": info.get("webpage_url", "https://youtube.com"),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Unknown"),
            "requester": interaction.user,
        }

        state.queue.append(track)
        if not vc.is_playing() and not vc.is_paused():
            play_next(vc, guild_id)

        embed = discord.Embed(
            title=" ᴍᴜꜱɪᴄ ᴘᴀɴᴇʟ",
            description="Control your music with the buttons below!",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="🎶 Song",
            value=f"[{track['title']}]({track['webpage']})",
            inline=False,
        )
        embed.add_field(
            name="🎧 Requested By", value=track["requester"].mention, inline=True
        )
        embed.add_field(
            name="⏱ Duration",
            value=f"{int(track['duration']//60)}m {int(track['duration'] % 60)}s",
            inline=True,
        )
        embed.add_field(name="✍ Author", value=track["uploader"], inline=True)
        embed.set_author(
            name=track["requester"].display_name,
            icon_url=track["requester"].display_avatar.url,
        )
        embed.set_thumbnail(url=track["requester"].display_avatar.url)
        embed.set_footer(
            text=f"Requested by {track['requester'].display_name}",
            icon_url=track["requester"].display_avatar.url,
        )

        view = MusicControlView(vc, guild_id)
        await interaction.followup.send(embed=embed, view=view)

    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)


# --------------------
# /stop command
# --------------------
@tree.command(name="stop", description="Stop and leave")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
        music_states.pop(interaction.guild.id, None)
        await interaction.response.send_message("⏹️ Stopped and left")
    else:
        await interaction.response.send_message("❌ Not connected", ephemeral=True)


# --------------------
# Run Bot
# --------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")


bot.run(TOKEN)
