"""
SpeechLLM — Application Configuration

Centralizes all settings with sensible defaults for local development.
All values can be overridden via environment variables or .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).parent / ".env")


# ── Paths ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
VOSK_MODEL_PATH = os.getenv("VOSK_MODEL_PATH", str(BASE_DIR / "models" / "vosk-model-small-id"))

# ── Audio ────────────────────────────────────────────────────
AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
AUDIO_CHANNELS = int(os.getenv("AUDIO_CHANNELS", "1"))
AUDIO_BLOCK_SIZE = 512          # samples per VAD frame (~32ms at 16kHz)
AUDIO_DTYPE = "int16"

# ── Silero VAD ───────────────────────────────────────────────
VAD_THRESHOLD = 0.5             # speech probability threshold
VAD_MIN_SPEECH_MS = 150         # minimum speech duration to trigger recognition
VAD_MAX_SPEECH_MS = 3000        # maximum speech segment (children babble short)
VAD_SILENCE_MS = 500            # silence after speech to finalize segment

# ── Vosk Recognizer ──────────────────────────────────────────
VOSK_LOG_LEVEL = -1             # suppress Vosk logs

# ── Phoneme Extraction ───────────────────────────────────────
PHONEME_CONFIDENCE_THRESHOLD = 0.4    # minimum confidence to accept a phoneme
PHONEME_FUZZY_MAX_DISTANCE = 1        # Levenshtein distance for fuzzy matching

# ── Semantic Router ──────────────────────────────────────────
GEMINI_USAGE_PERCENT = int(os.getenv("GEMINI_USAGE_PERCENT", "30"))  # % of responses using Gemini

# ── Gemini API ───────────────────────────────────────────────
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_TIMEOUT_S = float(os.getenv("GEMINI_TIMEOUT_MS", "2000")) / 1000
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.7"))
GEMINI_MAX_OUTPUT_TOKENS = 40   # hard cap — responses must be ≤10 words

# ── Response Filter ──────────────────────────────────────────
MAX_RESPONSE_WORDS = 10         # speech therapy constraint
MIN_RESPONSE_WORDS = 2          # too short = probably garbage

# ── Server ───────────────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# ── Target Age Group ─────────────────────────────────────────
# 18-36 months: early words stage, simple CVCV words, 1-2 word combinations
TARGET_AGE_MONTHS_MIN = 18
TARGET_AGE_MONTHS_MAX = 36
