"""
Semantic Router

Decides how to respond to a detected phoneme, and is the single entry point for
the whole response path.

On the device `gemini_client` is always None, so every response is a template —
which is what makes it playable from the pre-rendered SD card. The Gemini branch
exists for the dev server; any failure in it falls through to a template, so the
child never gets an error.

The returned TherapyResponse carries `bank_phoneme`/`bank_variant`, identifying
exactly which pre-rendered phrase was chosen. The device maps that pair to a
track number; it never matches on the text.
"""

import logging
import random
import time
from dataclasses import dataclass

from speechllm_core.detection.phonemes import PhonemeResult
from speechllm_core.routing.intents import TherapeuticIntent, get_intent
from speechllm_core.routing.templates import get_noise_fallback_variant, pick_template_variant
from speechllm_core.settings import settings

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

    # Which pre-rendered phrase this is, for SD-card playback. None means the
    # text was generated at runtime (Gemini) and has no track on the card, so a
    # DFPlayer-only device cannot speak it.
    bank_phoneme: str | None = None
    bank_variant: int | None = None


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
            gemini_client: Optional GeminiClient. None (the device default)
                           means every response comes from a template.
        """
        self._gemini = gemini_client
        self._gemini_percent = settings.gemini_usage_percent

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
                or phoneme_result.confidence < settings.phoneme_confidence_threshold):
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
        bank_phoneme, variant, text = pick_template_variant(phoneme_result.phoneme)
        elapsed = (time.monotonic() - start) * 1000

        return TherapyResponse(
            text=text,
            source="template",
            phoneme=phoneme_result.phoneme,
            intent_category=intent.category,
            technique=intent.technique,
            latency_ms=elapsed,
            confidence=phoneme_result.confidence,
            bank_phoneme=bank_phoneme,
            bank_variant=variant,
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
        bank_phoneme, variant, text = get_noise_fallback_variant()
        elapsed = (time.monotonic() - start) * 1000

        return TherapyResponse(
            text=text,
            source="fallback",
            phoneme=phoneme_result.phoneme,
            intent_category="noise_fallback",
            technique="redirect",
            latency_ms=elapsed,
            confidence=phoneme_result.confidence,
            bank_phoneme=bank_phoneme,
            bank_variant=variant,
        )
