"""
Tests for the response filter

Validates that the LLM output filter correctly accepts/rejects responses.
"""

from speechllm_core.generation.response_filter import validate_response


class TestValidResponses:
    """Responses that should pass the filter."""

    def test_normal_expansion(self):
        assert validate_response("Ayah! Wah pintar, coba bilang Ayah!") is not None

    def test_normal_modeling(self):
        assert validate_response("Mama! Iya Mama di sini sayang!") is not None

    def test_short_response(self):
        assert validate_response("Bagus! Coba lagi!") is not None

    def test_exclamation_heavy(self):
        assert validate_response("Wah pintar! Ayo coba lagi!") is not None


class TestRejectedResponses:
    """Responses that should be rejected by the filter."""

    def test_too_many_words(self):
        long = "Ini adalah kalimat yang sangat panjang dan melebihi batas sepuluh kata yang sudah ditentukan oleh aturan"
        assert validate_response(long) is None

    def test_empty_string(self):
        assert validate_response("") is None

    def test_whitespace_only(self):
        assert validate_response("   ") is None

    def test_complex_vocabulary(self):
        assert validate_response("Stimulasi perkembangan komunikasi anak") is None

    def test_markdown_bold(self):
        assert validate_response("**Mama** di sini sayang!") is None

    def test_numbered_list(self):
        assert validate_response("1. Bilang mama dulu ya") is None

    def test_meta_commentary(self):
        assert validate_response("Catatan: ini contoh respons yang bagus") is None

    def test_non_indonesian(self):
        assert validate_response("Hello how are you today?") is None


class TestEdgeCases:
    """Edge cases and salvage logic."""

    def test_salvage_truncation(self):
        # Has two sentences, first is valid
        text = "Mama! Iya Mama sayang! Ini kalimat tambahan yang tidak perlu dan terlalu panjang"
        result = validate_response(text)
        # Should try to salvage first sentence
        if result is not None:
            assert len(result.split()) <= 10
