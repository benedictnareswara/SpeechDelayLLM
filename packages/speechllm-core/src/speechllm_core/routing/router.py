"""
Semantic Router

Decides how to respond to a detected phoneme, and is the single entry point for
the whole response path.

Every response is a template, which is what makes it playable from the
pre-rendered SD card: the device can only say "play track 47", so a response
with no track on the card is unspeakable by construction.

The returned TherapyResponse carries `bank_phoneme`/`bank_variant`, identifying
exactly which pre-rendered phrase was chosen. The device maps that pair to a
track number; it never matches on the text.
"""

import logging
import time
from dataclasses import dataclass

from speechllm_core.detection.phonemes import PhonemeResult
from speechllm_core.routing.intents import get_intent
from speechllm_core.routing.templates import get_noise_fallback_variant, pick_template_variant
from speechllm_core.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class TherapyResponse:
    """Final response to be spoken to the child."""
    text: str                    # the response text in Indonesian
    source: str                  # "template" | "fallback"
    phoneme: str                 # detected phoneme
    intent_category: str         # therapeutic intent category
    technique: str               # "expansion" | "modeling" | "redirect"
    latency_ms: float            # time to generate response
    confidence: float            # detection confidence

    # Which pre-rendered phrase this is, for SD-card playback. Always set now
    # that every response comes from the template pools, but kept optional so a
    # sink can still fail loudly rather than guess if that ever stops holding.
    bank_phoneme: str | None = None
    bank_variant: int | None = None


class SemanticRouter:
    """
    Routes detected phonemes to therapeutic responses.

    Flow:
    1. Reject noise / low-confidence detections
    2. Look up TherapeuticIntent
    3. Pick a template variant and report which one
    """

    def route(self, phoneme_result: PhonemeResult) -> TherapyResponse:
        """
        Route a phoneme detection to a therapeutic response.

        Args:
            phoneme_result: Output from phoneme_extractor.

        Returns:
            TherapyResponse identifying a track on the SD card.
        """
        start = time.monotonic()

        # ── 1. Reject noise / low confidence ─────────────────
        if (phoneme_result.phoneme == "NOISE"
                or phoneme_result.confidence < settings.phoneme_confidence_threshold):
            return self._make_fallback_response(phoneme_result, start)

        # ── 2. Look up intent ────────────────────────────────
        intent = get_intent(phoneme_result.phoneme)

        # ── 3. Template response ─────────────────────────────
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
