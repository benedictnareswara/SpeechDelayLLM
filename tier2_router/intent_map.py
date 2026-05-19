"""
Tier 2a — Therapeutic Intent Map

Maps canonical phonemes to TherapeuticIntent objects that define
how the system should respond. Based on:
- IDAI (Ikatan Dokter Anak Indonesia) developmental milestones
- Terapi Wicara expansion and modeling techniques
- Target age: 18–36 months (early words stage)
"""

from dataclasses import dataclass, field


@dataclass
class TherapeuticIntent:
    """Defines the therapeutic response strategy for a detected phoneme."""
    category: str                       # e.g., "vowel_expansion", "syllable_modeling"
    target_words: list[str]             # words to model, e.g. ["Ayah", "Apel"]
    technique: str                      # "expansion" | "modeling" | "melodic_response"
    emotion: str                        # "enthusiastic" | "gentle" | "playful"
    description: str = ""               # human-readable description for logging
    age_appropriate: bool = True        # suitable for 18-36 months
    repetition_cue: bool = True         # should encourage repetition


# ── Intent Registry ──────────────────────────────────────────
# Every canonical phoneme from phoneme_extractor maps to an intent.

INTENT_REGISTRY: dict[str, TherapeuticIntent] = {

    # ── Vowel Expansion ──────────────────────────────────────
    "A": TherapeuticIntent(
        category="vowel_expansion",
        target_words=["Ayah", "Apel", "Air", "Ayo"],
        technique="expansion",
        emotion="enthusiastic",
        description="Ekspansi vokal A → kata dengan awalan A",
    ),
    "I": TherapeuticIntent(
        category="vowel_expansion",
        target_words=["Ibu", "Ikan", "Ini", "Ingin"],
        technique="expansion",
        emotion="gentle",
        description="Ekspansi vokal I → kata dengan awalan I",
    ),
    "U": TherapeuticIntent(
        category="vowel_expansion",
        target_words=["Ubi", "Udang", "Untuk"],
        technique="expansion",
        emotion="playful",
        description="Ekspansi vokal U → kata dengan awalan U",
    ),
    "E": TherapeuticIntent(
        category="vowel_expansion",
        target_words=["Enak", "Es", "Elang"],
        technique="expansion",
        emotion="gentle",
        description="Ekspansi vokal E → kata dengan awalan E",
    ),
    "O": TherapeuticIntent(
        category="vowel_expansion",
        target_words=["Oke", "Orang", "Oleh"],
        technique="expansion",
        emotion="enthusiastic",
        description="Ekspansi vokal O → kata dengan awalan O",
    ),

    # ── Syllable Modeling (Bilabial — earliest consonants) ───
    "MA": TherapeuticIntent(
        category="syllable_modeling",
        target_words=["Mama", "Makan", "Mau", "Main"],
        technique="modeling",
        emotion="gentle",
        description="Modeling suku kata MA → kata keluarga/kegiatan",
    ),
    "BA": TherapeuticIntent(
        category="syllable_modeling",
        target_words=["Baju", "Bola", "Bapak", "Baik"],
        technique="modeling",
        emotion="playful",
        description="Modeling suku kata BA → kata benda/sifat",
    ),
    "PA": TherapeuticIntent(
        category="syllable_modeling",
        target_words=["Papa", "Pagi", "Panas", "Pintar"],
        technique="modeling",
        emotion="enthusiastic",
        description="Modeling suku kata PA → kata keluarga/waktu",
    ),

    # ── Syllable Modeling (Dental/Alveolar) ──────────────────
    "DA": TherapeuticIntent(
        category="syllable_modeling",
        target_words=["Dada", "Duduk", "Dua", "Dekat"],
        technique="modeling",
        emotion="playful",
        description="Modeling suku kata DA → kata gerakan/angka",
    ),
    "TA": TherapeuticIntent(
        category="syllable_modeling",
        target_words=["Tangan", "Tidur", "Tiga", "Topi"],
        technique="modeling",
        emotion="gentle",
        description="Modeling suku kata TA → kata tubuh/angka",
    ),
    "NA": TherapeuticIntent(
        category="syllable_modeling",
        target_words=["Nama", "Nasi", "Naik", "Nyanyi"],
        technique="modeling",
        emotion="gentle",
        description="Modeling suku kata NA → kata kegiatan/makanan",
    ),

    # ── Early Words (18-36 month milestones) ─────────────────
    "MAU": TherapeuticIntent(
        category="early_word_reinforcement",
        target_words=["Mau", "Mau makan", "Mau main", "Mau susu"],
        technique="expansion",
        emotion="enthusiastic",
        description="Penguatan kata 'mau' → ekspansi ke frasa",
    ),
    "ITU": TherapeuticIntent(
        category="early_word_reinforcement",
        target_words=["Itu", "Itu apa", "Itu bola", "Itu kucing"],
        technique="expansion",
        emotion="playful",
        description="Penguatan kata 'itu' → ekspansi ke frasa tunjuk",
    ),
    "INI": TherapeuticIntent(
        category="early_word_reinforcement",
        target_words=["Ini", "Ini buku", "Ini mama", "Ini adik"],
        technique="expansion",
        emotion="gentle",
        description="Penguatan kata 'ini' → ekspansi ke frasa tunjuk",
    ),
    "IYA": TherapeuticIntent(
        category="early_word_reinforcement",
        target_words=["Iya", "Iya mau", "Iya bagus", "Iya benar"],
        technique="expansion",
        emotion="enthusiastic",
        description="Penguatan kata 'iya' → afirmasi",
    ),
    "TIDAK": TherapeuticIntent(
        category="early_word_reinforcement",
        target_words=["Tidak", "Tidak mau", "Nggak", "Nggak mau"],
        technique="modeling",
        emotion="gentle",
        description="Penguatan kata 'tidak' → modeling penolakan sopan",
    ),
    "MAKAN": TherapeuticIntent(
        category="early_word_reinforcement",
        target_words=["Makan", "Makan nasi", "Makan enak", "Mau makan"],
        technique="expansion",
        emotion="playful",
        description="Penguatan kata 'makan' → ekspansi aktivitas",
    ),
    "MINUM": TherapeuticIntent(
        category="early_word_reinforcement",
        target_words=["Minum", "Minum air", "Minum susu", "Mau minum"],
        technique="expansion",
        emotion="gentle",
        description="Penguatan kata 'minum' → ekspansi aktivitas",
    ),
    "SUSU": TherapeuticIntent(
        category="early_word_reinforcement",
        target_words=["Susu", "Mau susu", "Susu enak", "Minum susu"],
        technique="expansion",
        emotion="enthusiastic",
        description="Penguatan kata 'susu' → ekspansi makanan",
    ),

    # ── Melodic Jargon ───────────────────────────────────────
    "JARGON": TherapeuticIntent(
        category="melodic_jargon_response",
        target_words=["Mama", "Papa", "Ayo"],
        technique="melodic_response",
        emotion="playful",
        description="Respons terhadap jargon melodis → redirect ke kata nyata",
    ),

    # ── Noise Fallback ───────────────────────────────────────
    "NOISE": TherapeuticIntent(
        category="noise_fallback",
        target_words=[],
        technique="redirect",
        emotion="calm",
        description="Suara tidak dikenali → ajakan lembut untuk bicara",
    ),
}


def get_intent(phoneme: str) -> TherapeuticIntent:
    """Look up therapeutic intent for a phoneme. Defaults to NOISE fallback."""
    return INTENT_REGISTRY.get(phoneme, INTENT_REGISTRY["NOISE"])
