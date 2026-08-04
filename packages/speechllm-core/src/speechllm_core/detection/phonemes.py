"""
Phoneme Extractor

Maps raw speech-recognition text to canonical phoneme categories.
Tailored for Indonesian children aged 18–36 months (early words stage).

This is the semantic chokepoint of the whole system: everything downstream
(intents, templates, phrase-bank tracks) is keyed on the labels produced here,
so adding a label means updating routing/intents.py and routing/templates.py
in lockstep. tools/verify_bank.py enforces that.

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

from speechllm_core.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class PhonemeResult:
    """Canonical phoneme extracted from raw speech input."""
    phoneme: str         # canonical label, e.g. "MA", "A", "NOISE"
    confidence: float    # combined recognizer + mapping confidence
    raw_text: str        # original recognizer output
    category: str        # "vowel", "syllable", "early_word", "noise"


# ── Exact Match Map ──────────────────────────────────────────
# Maps recognizer text output → (canonical_phoneme, category)
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
    # NOTE: "kucing" → "KUCING" was mapped here but had no entry in
    # routing/intents.py and no phrases in routing/templates.py, so it silently
    # degraded to the NOISE pool. Removed rather than left half-wired. To add it
    # for real, touch all three in lockstep — this map, INTENT_REGISTRY, and
    # TEMPLATES — then re-run tools/render_bank.py. test_bank.py enforces it.

    # ── Melodic Jargon (common babble patterns) ──
    "la":     ("JARGON", "jargon"),
    "lalala": ("JARGON", "jargon"),
    "nana":   ("NA", "syllable"),
    "dede":   ("DA", "syllable"),
    "bebe":   ("BA", "syllable"),
}


def extract_phoneme(raw_text: str, recognizer_confidence: float) -> PhonemeResult:
    """
    Extract canonical phoneme from recognized text.

    Strategy:
    1. Try exact match in PHONEME_MAP
    2. Try fuzzy match (Levenshtein distance ≤ threshold)
    3. Fall back to NOISE

    Args:
        raw_text: Lowercase text from the speech recognizer.
        recognizer_confidence: Recognizer confidence (0.0–1.0).

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
            confidence=recognizer_confidence,
            raw_text=raw_text,
            category=category,
        )

    # ── 2. Fuzzy Match ───────────────────────────────────────
    # Only attempt for short strings (babbling is typically 1-4 chars)
    if len(text) <= 5:
        best_match = None
        best_distance = settings.phoneme_fuzzy_max_distance + 1

        for key in PHONEME_MAP:
            dist = levenshtein_distance(text, key)
            if dist <= settings.phoneme_fuzzy_max_distance and dist < best_distance:
                best_distance = dist
                best_match = key

        if best_match is not None:
            phoneme, category = PHONEME_MAP[best_match]
            # Reduce confidence for fuzzy matches
            adjusted_confidence = recognizer_confidence * (1.0 - 0.3 * best_distance)
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
        return extract_phoneme(words[0], recognizer_confidence)

    # ── 4. Fall back to NOISE ────────────────────────────────
    logger.debug("No phoneme match for: '%s'", text)
    return PhonemeResult(
        phoneme="NOISE", confidence=0.0,
        raw_text=raw_text, category="noise"
    )
