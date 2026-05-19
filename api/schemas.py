"""
API Schemas — Pydantic models for request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Optional


# ── Response Models ──────────────────────────────────────────

class TherapyResponseSchema(BaseModel):
    """Response returned after processing audio or text input."""
    text: str = Field(..., description="Therapeutic response in Indonesian")
    source: str = Field(..., description="Response source: 'template', 'gemini', or 'fallback'")
    phoneme: str = Field(..., description="Detected canonical phoneme")
    intent_category: str = Field(..., description="Therapeutic intent category")
    technique: str = Field(..., description="Technique used: expansion, modeling, etc.")
    latency_ms: float = Field(..., description="Response generation time in milliseconds")
    confidence: float = Field(..., description="Detection confidence 0.0–1.0")


class TextInputRequest(BaseModel):
    """Direct text input for testing without microphone."""
    text: str = Field(..., description="Simulated child speech text (e.g., 'ma', 'a', 'mau')")


class HealthResponse(BaseModel):
    """System health check response."""
    status: str
    vosk_loaded: bool
    vad_loaded: bool
    gemini_available: bool
    version: str = "0.1.0"


class PipelineStatusResponse(BaseModel):
    """Status of the audio processing pipeline."""
    is_running: bool
    total_detections: int
    total_responses: int
    avg_latency_ms: float
