"""
Tests for Tier 2 — Semantic Router

Validates routing logic, template selection, and fallback behavior.
"""

import pytest
import pytest_asyncio

from tier1_detector.phoneme_extractor import PhonemeResult
from tier2_router.router import SemanticRouter, TherapyResponse
from tier2_router.intent_map import INTENT_REGISTRY, get_intent
from tier2_router.templates import TEMPLATES, pick_template


class TestIntentMap:
    """Test intent registry completeness and correctness."""

    def test_all_phonemes_have_intents(self):
        required = ["A", "I", "U", "E", "O", "MA", "BA", "PA", "DA", "TA", "NA",
                     "MAU", "ITU", "INI", "IYA", "TIDAK", "MAKAN", "MINUM", "SUSU",
                     "JARGON", "NOISE"]
        for phoneme in required:
            assert phoneme in INTENT_REGISTRY, f"Missing intent for {phoneme}"

    def test_noise_intent_has_no_target_words(self):
        intent = get_intent("NOISE")
        assert intent.target_words == []
        assert intent.technique == "redirect"

    def test_vowel_intents_use_expansion(self):
        for phoneme in ["A", "I", "U", "E", "O"]:
            intent = get_intent(phoneme)
            assert intent.technique == "expansion"

    def test_syllable_intents_use_modeling(self):
        for phoneme in ["MA", "BA", "PA", "DA", "TA", "NA"]:
            intent = get_intent(phoneme)
            assert intent.technique == "modeling"

    def test_unknown_phoneme_returns_noise(self):
        intent = get_intent("ZZZZ")
        assert intent.category == "noise_fallback"


class TestTemplates:
    """Test template response pools."""

    def test_all_intents_have_templates(self):
        for phoneme in INTENT_REGISTRY:
            assert phoneme in TEMPLATES, f"No template pool for {phoneme}"

    def test_template_pools_have_variety(self):
        for phoneme, pool in TEMPLATES.items():
            assert len(pool) >= 3, f"{phoneme} has too few templates ({len(pool)})"

    def test_templates_under_word_limit(self):
        for phoneme, pool in TEMPLATES.items():
            for template in pool:
                word_count = len(template.split())
                assert word_count <= 10, (
                    f"{phoneme}: '{template}' has {word_count} words (max 10)"
                )

    def test_pick_template_returns_string(self):
        result = pick_template("MA")
        assert isinstance(result, str)
        assert len(result) > 0


class TestSemanticRouter:
    """Test routing logic."""

    @pytest.fixture
    def router(self):
        return SemanticRouter(gemini_client=None)  # template-only mode

    @pytest.mark.asyncio
    async def test_route_known_phoneme(self, router):
        phoneme = PhonemeResult(phoneme="MA", confidence=0.9, raw_text="ma", category="syllable")
        response = await router.route(phoneme)
        assert response.source == "template"
        assert response.phoneme == "MA"
        assert response.technique == "modeling"

    @pytest.mark.asyncio
    async def test_route_noise_returns_fallback(self, router):
        phoneme = PhonemeResult(phoneme="NOISE", confidence=0.1, raw_text="", category="noise")
        response = await router.route(phoneme)
        assert response.source == "fallback"
        assert response.intent_category == "noise_fallback"

    @pytest.mark.asyncio
    async def test_route_low_confidence_returns_fallback(self, router):
        phoneme = PhonemeResult(phoneme="MA", confidence=0.1, raw_text="ma", category="syllable")
        response = await router.route(phoneme)
        assert response.source == "fallback"

    @pytest.mark.asyncio
    async def test_response_has_latency(self, router):
        phoneme = PhonemeResult(phoneme="A", confidence=0.9, raw_text="a", category="vowel")
        response = await router.route(phoneme)
        assert response.latency_ms >= 0
        assert response.latency_ms < 100  # templates should be < 1ms
