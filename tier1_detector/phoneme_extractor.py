"""
Tier 1c — Phoneme Extractor

Maps raw Vosk text output to canonical phoneme categories.
Tailored for Indonesian children aged 18–36 months (early words stage).

At this stage, children typically produce:
- Clear vowels: A, I, U, E, O
- Bilabial consonants: M, B, P
- Early CVCV words: Mama, Papa, Baba
- Dental/alveolar: D, T, N
- Some early words: mau, itu, ini
"""

import logging
from dataclasses import dataclass

from Levenshtein import distance as levenshtein_distance

import config

logger = logging.getLogger(__name__)


@dataclass
class PhonemeResult:
    """Canonical phoneme extracted from raw speech input."""
    phoneme: str         # canonical label, e.g. "MA", "A", "NOISE"
    confidence: float    # combined Vosk + mapping confidence
    raw_text: str        # original Vosk output
    category: str        # "vowel", "syllable", "early_word", "noise"


# ── Exact Match Map ──────────────────────────────────────────
# Maps Vosk text output → (canonical_phoneme, category)
# Ordered by frequency in Indonesian child speech (18-36mo)
PHONEME_MAP: dict[str, tuple[str, str]] = {
    # ── Pure Vowels ──
    "a":     ("A", "vowel"),
    "ah":    ("A", "vowel"),
    "ha":    ("A", "vowel"),
    "aa":    ("A", "vowel"),
    "i":     ("I", "vowel"),
    "ih":    ("I", "vowel"),
    "hi":    ("I", "vowel"),
    "ii":    ("I", "vowel"),
    "u":     ("U", "vowel"),
    "uh":    ("U", "vowel"),
    "hu":    ("U", "vowel"),
    "uu":    ("U", "vowel"),
    "e":     ("E", "vowel"),
    "eh":    ("E", "vowel"),
    "he":    ("E", "vowel"),
    "o":     ("O", "vowel"),
    "oh":    ("O", "vowel"),
    "ho":    ("O", "vowel"),

    # ── Bilabial Syllables (earliest consonants) ──
    "ma":    ("MA", "syllable"),
    "mah":   ("MA", "syllable"),
    "mama":  ("MA", "syllable"),
    "mam":   ("MA", "syllable"),
    "ba":    ("BA", "syllable"),
    "bah":   ("BA", "syllable"),
    "baba":  ("BA", "syllable"),
    "pa":    ("PA", "syllable"),
    "pah":   ("PA", "syllable"),
    "papa":  ("PA", "syllable"),
    "pap":   ("PA", "syllable"),

    # ── Dental / Alveolar ──
    "da":    ("DA", "syllable"),
    "dah":   ("DA", "syllable"),
    "dada":  ("DA", "syllable"),
    "ta":    ("TA", "syllable"),
    "tah":   ("TA", "syllable"),
    "na":    ("NA", "syllable"),
    "nah":   ("NA", "syllable"),

    # ── Early Words (18-36 month milestones) ──
    "mau":   ("MAU", "early_word"),
    "mam":   ("MA", "syllable"),
    "itu":   ("ITU", "early_word"),
    "tu":    ("ITU", "early_word"),
    "ini":   ("INI", "early_word"),
    "ni":    ("INI", "early_word"),
    "iya":   ("IYA", "early_word"),
    "ya":    ("IYA", "early_word"),
    "yah":   ("IYA", "early_word"),
    "tidak": ("TIDAK", "early_word"),
    "dak":   ("TIDAK", "early_word"),
    "nggak": ("TIDAK", "early_word"),
    "gak":   ("TIDAK", "early_word"),
    "makan": ("MAKAN", "early_word"),
    "kan":   ("MAKAN", "early_word"),
    "minum": ("MINUM", "early_word"),
    "num":   ("MINUM", "early_word"),
    "susu":  ("SUSU", "early_word"),
    "su":    ("SUSU", "early_word"),
    "kucing":"KUCING",  # will be handled below

    # ── Melodic Jargon (common babble patterns) ──
    "la":    ("JARGON", "jargon"),
    "lalala":"JARGON",
    "nana":  ("NA", "syllable"),
    "dede":  ("DA", "syllable"),
    "bebe":  ("BA", "syllable"),
}

# Fix entries that aren't tuples (normalize)
for _key, _val in list(PHONEME_MAP.items()):
    if isinstance(_val, str):
        PHONEME_MAP[_key] = (_val, "early_word")


def extract_phoneme(raw_text: str, vosk_confidence: float) -> PhonemeResult:
    """
    Extract canonical phoneme from raw Vosk text output.

    Strategy:
    1. Try exact match in PHONEME_MAP
    2. Try fuzzy match (Levenshtein distance ≤ threshold)
    3. Fall back to NOISE

    Args:
        raw_text: Lowercase text from Vosk recognizer.
        vosk_confidence: Vosk word-level confidence (0.0–1.0).

    Returns:
        PhonemeResult with canonical phoneme label.
    """
    text = raw_text.strip().lower()

    # Empty input → noise
    if not text:
        return PhonemeResult(
            phoneme="NOISE", confidence=0.0,
            raw_text=raw_text, category="noise"
        )

    # ── 1. Exact Match ───────────────────────────────────────
    if text in PHONEME_MAP:
        phoneme, category = PHONEME_MAP[text]
        return PhonemeResult(
            phoneme=phoneme,
            confidence=vosk_confidence,
            raw_text=raw_text,
            category=category,
        )

    # ── 2. Fuzzy Match ───────────────────────────────────────
    # Only attempt for short strings (babbling is typically 1-4 chars)
    if len(text) <= 5:
        best_match = None
        best_distance = config.PHONEME_FUZZY_MAX_DISTANCE + 1

        for key in PHONEME_MAP:
            dist = levenshtein_distance(text, key)
            if dist <= config.PHONEME_FUZZY_MAX_DISTANCE and dist < best_distance:
                best_distance = dist
                best_match = key

        if best_match is not None:
            phoneme, category = PHONEME_MAP[best_match]
            # Reduce confidence for fuzzy matches
            adjusted_confidence = vosk_confidence * (1.0 - 0.3 * best_distance)
            logger.debug("Fuzzy match: '%s' → '%s' (dist=%d)", text, best_match, best_distance)
            return PhonemeResult(
                phoneme=phoneme,
                confidence=adjusted_confidence,
                raw_text=raw_text,
                category=category,
            )

    # ── 3. Multi-word input → take first word ────────────────
    words = text.split()
    if len(words) > 1:
        return extract_phoneme(words[0], vosk_confidence)

    # ── 4. Fall back to NOISE ────────────────────────────────
    logger.debug("No phoneme match for: '%s'", text)
    return PhonemeResult(
        phoneme="NOISE", confidence=0.0,
        raw_text=raw_text, category="noise"
    )
