"""
Text-to-Speech Module

Converts therapeutic response text to spoken audio.
Uses gTTS (Google Translate TTS) as a lightweight, free option.
Can be swapped for Gemini TTS or local espeak for RPi deployment.
"""

import io
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


async def speak_response(text: str, lang: str = "id") -> Path | None:
    """
    Convert text to speech and save as temporary audio file.

    Args:
        text: Indonesian text to speak.
        lang: Language code (default: "id" for Indonesian).

    Returns:
        Path to the generated audio file, or None on failure.
    """
    try:
        from gtts import gTTS
        import asyncio

        def _generate():
            tts = gTTS(text=text, lang=lang, slow=True)  # slow=True for clarity
            # Save to temp file
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tts.save(tmp.name)
            return Path(tmp.name)

        loop = asyncio.get_event_loop()
        path = await loop.run_in_executor(None, _generate)
        logger.info("TTS generated: %s → %s", text, path)
        return path

    except ImportError:
        logger.warning("gTTS not installed. Skipping TTS.")
        return None
    except Exception as e:
        logger.error("TTS error: %s", e)
        return None
