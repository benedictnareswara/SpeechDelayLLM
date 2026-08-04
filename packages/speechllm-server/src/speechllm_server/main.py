"""
FastAPI Application — Entry Point

Development harness only. This runs on a laptop so routing logic can be poked
at over HTTP; it is never installed on the Orange Pi, which has no web server
and no network. Use `python -m speechllm_device` for the real thing.

Run with: uvicorn speechllm_server.main:app --reload
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from speechllm_core.bank.manifest import BankManifest
from speechllm_core.routing.router import SemanticRouter
from speechllm_core.settings import settings

from speechllm_server.routes import init_routes, router

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
        "gemini_available": False,
        "bank_valid": False,
        "bank_tracks": 0,
        "version": "0.2.0",
    }

    # ── Gemini (optional) ────────────────────────────────────
    gemini_client = None
    if settings.google_api_key:
        try:
            from speechllm_core.generation.gemini_client import GeminiClient
            gemini_client = GeminiClient()
            health["gemini_available"] = True
            logger.info("✅ Gemini client initialized")
        except Exception as e:
            logger.warning("⚠️  Gemini unavailable — %s", e)
            logger.info("   Serving template-only responses")
    else:
        logger.warning("⚠️  GOOGLE_API_KEY not set — serving template-only responses")

    # ── Router ───────────────────────────────────────────────
    semantic_router = SemanticRouter(gemini_client=gemini_client)
    logger.info("✅ Semantic router initialized")

    # ── Phrase bank ──────────────────────────────────────────
    # Reported but not enforced: the dev server prints responses rather than
    # playing them, so a stale bank is informational here. The device refuses
    # to start on the same mismatch.
    try:
        manifest = BankManifest.load(settings.bank_manifest)
        problems = manifest.validate_against_templates()
        health["bank_valid"] = not problems
        health["bank_tracks"] = len(manifest.tracks)
        if problems:
            logger.warning("⚠️  Phrase bank is stale (%d problems) — run tools/render_bank.py",
                           len(problems))
        else:
            logger.info("✅ Phrase bank: %d tracks", len(manifest.tracks))
    except FileNotFoundError:
        logger.info("ℹ️  No phrase bank rendered yet (tools/render_bank.py)")
    except Exception as e:  # noqa: BLE001
        logger.warning("⚠️  Could not read the phrase bank: %s", e)

    # ── Initialize Routes ────────────────────────────────────
    init_routes(semantic_router, health)

    logger.info("═" * 60)
    logger.info("  SpeechLLM Dev Server Ready  (laptop harness — not the device)")
    logger.info("  API: http://%s:%d", settings.api_host, settings.api_port)
    logger.info("  Docs: http://%s:%d/docs", settings.api_host, settings.api_port)
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
    version="0.2.0",
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
