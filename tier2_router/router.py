"""
Tier 2b — Semantic Router

Core routing logic that decides how to respond to a detected phoneme.
Implements the 70/30 template/Gemini split for optimal latency vs variety.
"""

import logging
import random
import time
from dataclasses import dataclass

from tier1_detector.phoneme_extractor import PhonemeResult
from tier2_router.intent_map import TherapeuticIntent, get_intent
from tier2_router.templates import pick_template, get_noise_fallback

import config

logger = logging.getLogger(__name__)


@dataclass
class TherapyResponse:
    """Final response to be spoken/displayed to the child."""
    text: str                    # the response text in Indonesian
    source: str                  # "template" | "gemini" | "fallback"
    phoneme: str                 # detected phoneme
    intent_category: str         # therapeutic intent category
    technique: str               # "expansion" | "modeling" | "redirect"
    latency_ms: float            # time to generate response
    confidence: float            # detection confidence


class SemanticRouter:
    """
    Routes detected phonemes to appropriate therapeutic responses.

    Flow:
    1. Reject noise / low-confidence detections
    2. Look up TherapeuticIntent
    3. Decide: template (fast, 70%) vs Gemini (variety, 30%)
    4. Return TherapyResponse
    """

    def __init__(self, gemini_client=None):
        """
        Args:
            gemini_client: Optional Tier 3 GeminiClient instance.
                           If None, all responses use templates.
        """
        self._gemini = gemini_client
        self._gemini_percent = config.GEMINI_USAGE_PERCENT

    async def route(self, phoneme_result: PhonemeResult) -> TherapyResponse:
        """
        Route a phoneme detection to a therapeutic response.

        Args:
            phoneme_result: Output from phoneme_extractor.

        Returns:
            TherapyResponse ready for TTS or display.
        """
        start = time.monotonic()

        # ── 1. Reject noise / low confidence ─────────────────
        if (phoneme_result.phoneme == "NOISE"
                or phoneme_result.confidence < config.PHONEME_CONFIDENCE_THRESHOLD):
            return self._make_fallback_response(phoneme_result, start)

        # ── 2. Look up intent ────────────────────────────────
        intent = get_intent(phoneme_result.phoneme)

        # ── 3. Decide source ─────────────────────────────────
        use_gemini = (
            self._gemini is not None
            and random.randint(1, 100) <= self._gemini_percent
        )

        if use_gemini:
            response = await self._try_gemini(phoneme_result, intent, start)
            if response is not None:
                return response
            # Gemini failed — fall through to template
            logger.warning("Gemini failed, falling back to template")

        # ── 4. Template response ─────────────────────────────
        text = pick_template(phoneme_result.phoneme)
        elapsed = (time.monotonic() - start) * 1000

        return TherapyResponse(
            text=text,
            source="template",
            phoneme=phoneme_result.phoneme,
            intent_category=intent.category,
            technique=intent.technique,
            latency_ms=elapsed,
            confidence=phoneme_result.confidence,
        )

    async def _try_gemini(
        self,
        phoneme_result: PhonemeResult,
        intent: TherapeuticIntent,
        start: float,
    ) -> TherapyResponse | None:
        """Attempt to generate a response via Gemini. Returns None on failure."""
        try:
            text = await self._gemini.generate(
                phoneme=phoneme_result.phoneme,
                raw_text=phoneme_result.raw_text,
                intent=intent,
            )
            elapsed = (time.monotonic() - start) * 1000

            if text:
                return TherapyResponse(
                    text=text,
                    source="gemini",
                    phoneme=phoneme_result.phoneme,
                    intent_category=intent.category,
                    technique=intent.technique,
                    latency_ms=elapsed,
                    confidence=phoneme_result.confidence,
                )
        except Exception as e:
            logger.error("Gemini generation error: %s", e)

        return None

    def _make_fallback_response(
        self, phoneme_result: PhonemeResult, start: float
    ) -> TherapyResponse:
        """Generate a gentle fallback for noise/low-confidence input."""
        text = get_noise_fallback()
        elapsed = (time.monotonic() - start) * 1000

        return TherapyResponse(
            text=text,
            source="fallback",
            phoneme=phoneme_result.phoneme,
            intent_category="noise_fallback",
            technique="redirect",
            latency_ms=elapsed,
            confidence=phoneme_result.confidence,
        )
