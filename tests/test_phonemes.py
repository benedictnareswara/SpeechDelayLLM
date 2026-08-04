"""
Tests for the phoneme extractor

Validates phoneme mapping, fuzzy matching, and edge cases.
"""

from speechllm_core.detection.phonemes import extract_phoneme


class TestExactMatch:
    """Test exact phoneme matching from PHONEME_MAP."""

    def test_vowel_a(self):
        result = extract_phoneme("a", 0.9)
        assert result.phoneme == "A"
        assert result.category == "vowel"

    def test_vowel_i(self):
        result = extract_phoneme("i", 0.85)
        assert result.phoneme == "I"

    def test_vowel_u(self):
        result = extract_phoneme("u", 0.8)
        assert result.phoneme == "U"

    def test_syllable_ma(self):
        result = extract_phoneme("ma", 0.9)
        assert result.phoneme == "MA"
        assert result.category == "syllable"

    def test_syllable_mama(self):
        result = extract_phoneme("mama", 0.95)
        assert result.phoneme == "MA"

    def test_syllable_ba(self):
        result = extract_phoneme("ba", 0.88)
        assert result.phoneme == "BA"

    def test_syllable_pa(self):
        result = extract_phoneme("pa", 0.9)
        assert result.phoneme == "PA"

    def test_syllable_papa(self):
        result = extract_phoneme("papa", 0.92)
        assert result.phoneme == "PA"

    def test_early_word_mau(self):
        result = extract_phoneme("mau", 0.9)
        assert result.phoneme == "MAU"
        assert result.category == "early_word"

    def test_early_word_susu(self):
        result = extract_phoneme("susu", 0.85)
        assert result.phoneme == "SUSU"

    def test_early_word_iya(self):
        result = extract_phoneme("iya", 0.9)
        assert result.phoneme == "IYA"

    def test_early_word_tidak(self):
        result = extract_phoneme("tidak", 0.8)
        assert result.phoneme == "TIDAK"


class TestFuzzyMatch:
    """Test fuzzy matching for misrecognized babbles."""

    def test_mah_to_ma(self):
        result = extract_phoneme("mah", 0.7)
        assert result.phoneme == "MA"

    def test_bah_to_ba(self):
        result = extract_phoneme("bah", 0.7)
        assert result.phoneme == "BA"

    def test_pah_to_pa(self):
        result = extract_phoneme("pah", 0.75)
        assert result.phoneme == "PA"

    def test_fuzzy_confidence_reduced(self):
        exact = extract_phoneme("ma", 0.9)
        fuzzy = extract_phoneme("mx", 0.9)  # 1 edit distance from "ma"
        # Fuzzy match should have lower confidence
        if fuzzy.phoneme != "NOISE":
            assert fuzzy.confidence < exact.confidence


class TestNoiseHandling:
    """Test noise and edge case handling."""

    def test_empty_string(self):
        result = extract_phoneme("", 0.0)
        assert result.phoneme == "NOISE"
        assert result.category == "noise"

    def test_whitespace(self):
        result = extract_phoneme("   ", 0.0)
        assert result.phoneme == "NOISE"

    def test_unknown_long_word(self):
        result = extract_phoneme("abcdefghijk", 0.5)
        assert result.phoneme == "NOISE"

    def test_multi_word_takes_first(self):
        result = extract_phoneme("ma ma", 0.8)
        assert result.phoneme == "MA"


class TestCaseInsensitivity:
    """Ensure case doesn't affect matching."""

    def test_uppercase_a(self):
        result = extract_phoneme("A", 0.9)
        assert result.phoneme == "A"

    def test_mixed_case(self):
        result = extract_phoneme("Ma", 0.9)
        assert result.phoneme == "MA"
