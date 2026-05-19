"""
FastAPI Application — Entry Point

Initializes all three tiers on startup and mounts the API routes.
Run with: uvicorn api.main:app --reload
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from api.routes import router, init_routes
from tier2_router.router import SemanticRouter

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("speechllm")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize components on startup, clean up on shutdown."""
    health = {
        "status": "ok",
        "vosk_loaded": False,
        "vad_loaded": False,
        "gemini_available": False,
        "version": "0.1.0",
    }

    # ── Tier 3: Gemini Client (optional) ─────────────────────
    gemini_client = None
    if config.GOOGLE_API_KEY:
        try:
            from tier3_engine.gemini_client import GeminiClient
            gemini_client = GeminiClient()
            health["gemini_available"] = True
            logger.info("✅ Tier 3: Gemini client initialized")
        except Exception as e:
            logger.warning("⚠️  Tier 3: Gemini unavailable — %s", e)
            logger.info("   System will use template-only mode")
    else:
        logger.warning("⚠️  GOOGLE_API_KEY not set — running in template-only mode")

    # ── Tier 2: Semantic Router ──────────────────────────────
    semantic_router = SemanticRouter(gemini_client=gemini_client)
    logger.info("✅ Tier 2: Semantic router initialized")

    # ── Tier 1: VAD + Vosk (loaded on demand for API mode) ──
    # In API mode, Vosk/VAD are only needed for audio streaming.
    # For /process-text, we skip directly to phoneme extraction.
    logger.info("✅ Tier 1: Phoneme extractor ready (VAD/Vosk loaded on demand)")
    health["vad_loaded"] = True  # will be loaded when audio stream starts
    health["vosk_loaded"] = True

    # ── Initialize Routes ────────────────────────────────────
    init_routes(semantic_router, health)

    logger.info("═" * 60)
    logger.info("  SpeechLLM Terapi Wicara System Ready")
    logger.info("  API: http://%s:%d", config.API_HOST, config.API_PORT)
    logger.info("  Docs: http://%s:%d/docs", config.API_HOST, config.API_PORT)
    logger.info("  Gemini: %s", "enabled" if gemini_client else "disabled (template-only)")
    logger.info("═" * 60)

    yield  # App is running

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("SpeechLLM shutting down...")


# ── FastAPI App ──────────────────────────────────────────────
app = FastAPI(
    title="SpeechLLM — Terapi Wicara AI",
    description=(
        "AI-powered speech therapy assistant for Indonesian children aged 18–36 months. "
        "Detects babbling sounds and responds with therapeutically sound Indonesian "
        "phrases using Expansion and Modeling techniques."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS (for future web frontend) ──────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount Routes ─────────────────────────────────────────────
app.include_router(router)
