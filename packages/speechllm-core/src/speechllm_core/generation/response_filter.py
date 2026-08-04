"""
Response Filter

Validates LLM output to ensure it meets speech therapy constraints
before it reaches the child. Acts as a safety net against hallucination.

Rejection criteria:
- More than MAX_RESPONSE_WORDS words
- Less than MIN_RESPONSE_WORDS words
- Contains non-Indonesian content
- Contains complex/adult vocabulary
- Contains unwanted formatting (markdown, emoji-heavy, etc.)
"""

import logging
import re

from speechllm_core.settings import settings

logger = logging.getLogger(__name__)

# ── Blocklist: words too complex for 18-36 month interaction ──
COMPLEX_WORDS = {
    "seharusnya", "sebaiknya", "meskipun", "walaupun", "namun",
    "selanjutnya", "oleh karena itu", "berdasarkan", "merupakan",
    "melakukan", "menggunakan", "memperhatikan", "mempertimbangkan",
    "perkembangan", "kemampuan", "aktivitas", "pembelajaran",
    "stimulasi", "interaksi", "artikulasi", "komunikasi",
    "terapis", "diagnosis", "evaluasi", "konsultasi",
}

# ── Patterns that indicate LLM broke character ──────────────
BROKEN_PATTERNS = [
    r"(?i)^(catatan|note|penjelasan|keterangan):",  # added explanation
    r"(?i)^(berikut|ini adalah|contoh)",              # meta-commentary
    r"\*\*",                                           # markdown bold
    r"^-\s",                                           # markdown list
    r"^\d+\.\s",                                       # numbered list
    r"[🎤🔊💡📝]",                                     # specific emojis indicating meta-content
]


def validate_response(text: str) -> str | None:
    """
    Validate a Gemini response against therapy constraints.

    Args:
        text: Raw text from Gemini.

    Returns:
        Cleaned text if valid, None if rejected.
    """
    if not text or not text.strip():
        return None

    # Clean up whitespace
    cleaned = " ".join(text.strip().split())

    # ── Word count check ─────────────────────────────────────
    word_count = len(cleaned.split())
    if word_count > settings.max_response_words:
        logger.debug("Rejected: too many words (%d > %d)", word_count, settings.max_response_words)
        # Try to salvage by truncating to first sentence
        first_sentence = cleaned.split("!")[0] + "!" if "!" in cleaned else None
        if first_sentence and len(first_sentence.split()) <= settings.max_response_words:
            cleaned = first_sentence
        else:
            return None

    if word_count < settings.min_response_words:
        logger.debug("Rejected: too few words (%d < %d)", word_count, settings.min_response_words)
        return None

    # ── Complex vocabulary check ─────────────────────────────
    lower = cleaned.lower()
    for word in COMPLEX_WORDS:
        if word in lower:
            logger.debug("Rejected: complex word '%s'", word)
            return None

    # ── Broken character patterns ────────────────────────────
    for pattern in BROKEN_PATTERNS:
        if re.search(pattern, cleaned):
            logger.debug("Rejected: broken character pattern '%s'", pattern)
            return None

    # ── Basic Indonesian check ───────────────────────────────
    # Simple heuristic: response should contain at least one common
    # Indonesian word or exclamation
    indo_markers = {
        "ayo", "yuk", "coba", "bilang", "pintar", "hebat", "bagus",
        "mama", "papa", "ayah", "ibu", "sayang", "mau", "iya",
        "lagi", "enak", "main", "makan", "minum", "susu", "oke",
        "wah", "hore", "sini", "lihat",
    }
    words_lower = set(lower.replace("!", "").replace(",", "").replace("?", "").split())
    if not words_lower.intersection(indo_markers):
        logger.debug("Rejected: no Indonesian markers found")
        return None

    return cleaned
