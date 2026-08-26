"""Discord voice-channel announcements for race events."""

import asyncio
import logging
import random
import tempfile
from pathlib import Path

import discord
import pyttsx3

logger = logging.getLogger(__name__)


class VoiceAnnouncer:
    """Generate local speech and play announcements sequentially in voice chat."""

    def __init__(self) -> None:
        self._queues: dict[int, asyncio.Queue[tuple[str, str | Path]]] = {}
        self._workers: dict[int, asyncio.Task[None]] = {}
        self.player_joined_audio = Path.cwd() / "audio" / "player_joined.mp3"
        self.ready_error_audio = Path.cwd() / "audio" / "ready_error.mp3"
        self.countdown_audio_directory = Path.cwd() / "audio" / "countdown"

    async def announce(self, voice_client: discord.VoiceClient, text: str) -> None:
        queue = self._queues.setdefault(voice_client.guild.id, asyncio.Queue())
        await queue.put(("tts", text))
        worker = self._workers.get(voice_client.guild.id)
        if worker is None or worker.done():
            self._workers[voice_client.guild.id] = asyncio.create_task(
                self._play_queue(voice_client, queue)
            )

    async def announce_player_joined(self, voice_client: discord.VoiceClient) -> None:
        """Play the configured player-joined sound effect."""
        await self._announce_file(voice_client, self.player_joined_audio)

    async def announce_ready_error(self, voice_client: discord.VoiceClient) -> None:
        """Play the sound effect for an invalid attempt to start a race."""
        await self._announce_file(voice_client, self.ready_error_audio)

    async def announce_random_countdown(self, voice_client: discord.VoiceClient) -> None:
        """Play one randomly selected race-start sound effect."""
        audio_files = (
            [
                path
                for path in self.countdown_audio_directory.iterdir()
                if path.is_file() and path.suffix.casefold() in {".mp3", ".ogg", ".wav", ".m4a"}
            ]
            if self.countdown_audio_directory.is_dir()
            else []
        )
        if not audio_files:
            logger.warning("No countdown audio files found in %s", self.countdown_audio_directory)
            return
        await self._announce_file(voice_client, random.choice(audio_files))

    async def _announce_file(self, voice_client: discord.VoiceClient, audio_path: Path) -> None:
        queue = self._queues.setdefault(voice_client.guild.id, asyncio.Queue())
        await queue.put(("file", audio_path))
        worker = self._workers.get(voice_client.guild.id)
        if worker is None or worker.done():
            self._workers[voice_client.guild.id] = asyncio.create_task(
                self._play_queue(voice_client, queue)
            )

    async def _play_queue(
        self, voice_client: discord.VoiceClient, queue: asyncio.Queue[tuple[str, str | Path]]
    ) -> None:
        while not queue.empty():
            kind, value = await queue.get()
            audio_path: Path | None = None
            temporary_file = kind == "tts"
            try:
                audio_path = (
                    await asyncio.to_thread(self._create_audio_file, str(value))
                    if kind == "tts"
                    else Path(value)
                )
                if not audio_path.is_file():
                    raise FileNotFoundError(f"Audio file does not exist: {audio_path}")
                completed = asyncio.Event()
                loop = asyncio.get_running_loop()

                def after_playback(
                    error: Exception | None,
                    event_loop: asyncio.AbstractEventLoop = loop,
                    completion: asyncio.Event = completed,
                ) -> None:
                    if error:
                        logger.error("Voice announcement playback failed: %s", error)
                    event_loop.call_soon_threadsafe(completion.set)

                if not voice_client.is_connected():
                    logger.warning(
                        "Skipped announcement because the bot is no longer in voice chat."
                    )
                    continue
                voice_client.play(discord.FFmpegPCMAudio(str(audio_path)), after=after_playback)
                await completed.wait()
            except Exception:
                logger.exception("Could not play voice announcement: %s", value)
            finally:
                if temporary_file and audio_path:
                    audio_path.unlink(missing_ok=True)
                queue.task_done()

    @staticmethod
    def _create_audio_file(text: str) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output:
            path = Path(output.name)
        engine = pyttsx3.init()
        engine.save_to_file(text, str(path))
        engine.runAndWait()
        return path
