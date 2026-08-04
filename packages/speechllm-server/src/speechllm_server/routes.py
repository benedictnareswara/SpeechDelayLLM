"""
API Routes — REST and WebSocket endpoints.

Endpoints:
- GET  /health          → system health check
- POST /process-text    → simulate input without microphone (for testing)
- WS   /ws/stream       → real-time audio streaming (future)
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from speechllm_core.detection.phonemes import extract_phoneme
from speechllm_core.routing.router import SemanticRouter

from speechllm_server.schemas import (
    HealthResponse,
    TextInputRequest,
    TherapyResponseSchema,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# These are set during app startup in main.py
_semantic_router: SemanticRouter | None = None
_system_health: dict = {}


def init_routes(semantic_router: SemanticRouter, health: dict):
    """Initialize routes with dependencies from app startup."""
    global _semantic_router, _system_health
    _semantic_router = semantic_router
    _system_health = health


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """System health check — verify all components are loaded."""
    return HealthResponse(**_system_health)


@router.post("/process-text", response_model=TherapyResponseSchema)
async def process_text(request: TextInputRequest):
    """
    Process simulated text input (for testing without microphone).

    Send a child's babbling sound as text (e.g., "ma", "a", "susu")
    and receive the therapeutic response.
    """
    # Skip capture/VAD/STT: go straight from text to phoneme extraction.
    phoneme_result = extract_phoneme(request.text, recognizer_confidence=0.9)

    # Route to a response
    response = await _semantic_router.route(phoneme_result)

    logger.info(
        "Text input: '%s' → phoneme=%s → [%s] '%s' (%.0fms)",
        request.text, response.phoneme, response.source,
        response.text, response.latency_ms,
    )

    return TherapyResponseSchema(
        text=response.text,
        source=response.source,
        phoneme=response.phoneme,
        intent_category=response.intent_category,
        technique=response.technique,
        latency_ms=response.latency_ms,
        confidence=response.confidence,
        bank_phoneme=response.bank_phoneme,
        bank_variant=response.bank_variant,
    )


@router.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    """
    WebSocket endpoint for real-time audio streaming.

    Protocol:
    - Client sends: raw PCM int16 audio bytes (16kHz, mono)
    - Server sends: JSON TherapyResponseSchema on each detection
    """
    await websocket.accept()
    logger.info("WebSocket client connected")

    try:
        while True:
            # Receive text commands or audio bytes
            data = await websocket.receive_text()

            # For now, treat WebSocket text as simulated input
            phoneme_result = extract_phoneme(data, recognizer_confidence=0.8)
            response = await _semantic_router.route(phoneme_result)

            await websocket.send_json({
                "text": response.text,
                "source": response.source,
                "phoneme": response.phoneme,
                "intent_category": response.intent_category,
                "technique": response.technique,
                "latency_ms": response.latency_ms,
                "confidence": response.confidence,
            })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
