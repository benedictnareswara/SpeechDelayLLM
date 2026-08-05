"""
Tests for the semantic router

Validates routing logic, template selection, and fallback behavior.
"""

import pytest
from speechllm_core.detection.phonemes import PhonemeResult
from speechllm_core.routing.intents import INTENT_REGISTRY, get_intent
from speechllm_core.routing.router import SemanticRouter
from speechllm_core.routing.templates import TEMPLATES, pick_template_variant


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

    def test_pick_template_variant_identifies_its_own_choice(self):
        resolved, variant, text = pick_template_variant("MA")
        assert resolved == "MA"
        # The variant index must actually address the text that was returned —
        # the device looks up the SD-card track by (phoneme, variant), so a
        # mismatch here would play a different phrase than the one chosen.
        assert TEMPLATES[resolved][variant] == text

    def test_unknown_phoneme_resolves_to_noise_pool(self):
        resolved, variant, text = pick_template_variant("NOT_A_PHONEME")
        assert resolved == "NOISE"
        assert TEMPLATES["NOISE"][variant] == text


class TestSemanticRouter:
    """Test routing logic."""

    @pytest.fixture
    def router(self):
        return SemanticRouter()

    def test_route_known_phoneme(self, router):
        phoneme = PhonemeResult(phoneme="MA", confidence=0.9, raw_text="ma", category="syllable")
        response = router.route(phoneme)
        assert response.source == "template"
        assert response.phoneme == "MA"
        assert response.technique == "modeling"

    def test_route_noise_returns_fallback(self, router):
        phoneme = PhonemeResult(phoneme="NOISE", confidence=0.1, raw_text="", category="noise")
        response = router.route(phoneme)
        assert response.source == "fallback"
        assert response.intent_category == "noise_fallback"

    def test_route_low_confidence_returns_fallback(self, router):
        phoneme = PhonemeResult(phoneme="MA", confidence=0.1, raw_text="ma", category="syllable")
        response = router.route(phoneme)
        assert response.source == "fallback"

    def test_response_has_latency(self, router):
        phoneme = PhonemeResult(phoneme="A", confidence=0.9, raw_text="a", category="vowel")
        response = router.route(phoneme)
        assert response.latency_ms >= 0
        assert response.latency_ms < 100  # templates should be < 1ms

    def test_every_response_is_playable_from_the_card(self, router):
        """Every route must name a bank position, or the DFPlayer has nothing
        to play. This is the invariant that replaced the Gemini branch."""
        for label in ("MA", "A", "SUSU", "NOISE", "NOT_A_PHONEME"):
            response = router.route(
                PhonemeResult(phoneme=label, confidence=0.9, raw_text="x", category="syllable")
            )
            assert response.bank_phoneme in TEMPLATES
            assert 0 <= response.bank_variant < len(TEMPLATES[response.bank_phoneme])
