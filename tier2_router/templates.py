"""
Tier 2c — Hard-coded Response Templates

Pre-written, therapist-approved responses for each phoneme category.
These provide instant (<1ms) responses and serve as fallbacks when
Gemini is unavailable, slow, or produces invalid output.

All responses follow Terapi Wicara principles:
- Expansion: Take child's sound, expand to real word, praise
- Modeling: Provide correct word example with enthusiastic tone
- Max 10 words per response
- Warm, encouraging, promotes repetition
"""

import random


# ── Template Pools ───────────────────────────────────────────
# Each phoneme has 5+ response variants for natural variety.

TEMPLATES: dict[str, list[str]] = {

    # ── Vowel Expansion ──────────────────────────────────────
    "A": [
        "Ayah! Coba bilang Ayah, pintar!",
        "Aaa... Apel! Apel merah enak!",
        "Air! Mau minum air, sayang?",
        "Aaa bagus sekali! Coba lagi ya!",
        "Ayo! Ayo main sama Ayah!",
    ],
    "I": [
        "Ibu! Iya, Ibu di sini sayang!",
        "Ikan! Lihat ikan, bagus ya!",
        "Ini! Ini apa? Coba bilang!",
        "Iii pintar! Coba sekali lagi!",
        "Ibu sayang kamu! Coba lagi ya!",
    ],
    "U": [
        "Ubi! Wah ubi enak, coba bilang!",
        "Udang! Udang merah, yuk bilang!",
        "Uuu bagus! Pintar sekali kamu!",
        "Untuk kamu! Coba bilang untuk!",
        "Uuu hebat! Ayo coba lagi!",
    ],
    "E": [
        "Enak! Wah enak ya, coba bilang!",
        "Es! Mau es? Bilang eees!",
        "Eee bagus! Pintar, coba lagi!",
        "Elang! Burung elang terbang tinggi!",
        "Eee hebat! Ayo sekali lagi!",
    ],
    "O": [
        "Oke! Wah oke, pintar sekali!",
        "Ooo bagus! Coba lagi ya sayang!",
        "Orang! Lihat orang itu, yuk!",
        "Ooo hebat! Kamu pintar sekali!",
        "Oh iya! Bagus, coba lagi!",
    ],

    # ── Syllable Modeling ────────────────────────────────────
    "MA": [
        "Mama! Iya Mama di sini sayang!",
        "Makan! Yuk makan, enak!",
        "Mau! Kamu mau apa sayang?",
        "Mama sayang kamu! Coba lagi!",
        "Main! Ayo main sama Mama!",
    ],
    "BA": [
        "Bola! Mau main bola? Ayo!",
        "Baju! Wah baju bagus ya!",
        "Bapak! Coba bilang Bapak, pintar!",
        "Baik! Anak baik, hebat sekali!",
        "Bola! Lempar bola, yuk main!",
    ],
    "PA": [
        "Papa! Papa sayang kamu, hebat!",
        "Pagi! Selamat pagi, pintar!",
        "Pintar! Kamu pintar sekali, ayo!",
        "Papa! Coba bilang Papa lagi!",
        "Panas! Hati-hati panas ya sayang!",
    ],
    "DA": [
        "Dada! Dadah, bye bye! Pintar!",
        "Duduk! Ayo duduk, anak pintar!",
        "Dua! Satu, dua! Hebat!",
        "Dada! Coba bilang dada lagi!",
        "Dekat! Sini dekat Mama, yuk!",
    ],
    "TA": [
        "Tangan! Mana tangan? Coba bilang!",
        "Tidur! Ayo tidur, sayang!",
        "Tiga! Satu dua tiga, pintar!",
        "Topi! Pakai topi, bagus ya!",
        "Tangan! Tepuk tangan, hebat!",
    ],
    "NA": [
        "Nama! Siapa nama kamu? Pintar!",
        "Nasi! Mau nasi? Yuk makan!",
        "Naik! Ayo naik, hore!",
        "Nyanyi! Ayo nyanyi sama Mama!",
        "Nasi enak! Coba bilang nasi!",
    ],

    # ── Early Words ──────────────────────────────────────────
    "MAU": [
        "Mau! Mau apa sayang? Pintar!",
        "Mau makan? Ayo makan yuk!",
        "Mau main? Ayo main, hebat!",
        "Iya mau! Wah pintar bilang mau!",
        "Mau susu? Yuk minum susu!",
    ],
    "ITU": [
        "Itu! Itu apa? Coba bilang!",
        "Itu bola! Wah pintar sekali!",
        "Itu kucing! Lihat kucing lucu!",
        "Iya itu! Kamu pintar, hebat!",
        "Itu bagus! Coba bilang lagi!",
    ],
    "INI": [
        "Ini! Ini apa? Coba bilang!",
        "Ini buku! Wah suka buku ya!",
        "Ini Mama! Iya ini Mama!",
        "Ini bagus! Pintar bilang ini!",
        "Ini adik! Sayang adik ya!",
    ],
    "IYA": [
        "Iya! Wah pintar bilang iya!",
        "Iya benar! Kamu hebat sekali!",
        "Iya mau! Ayo kita main!",
        "Iya bagus! Pintar sekali sayang!",
        "Iya! Coba bilang iya lagi!",
    ],
    "TIDAK": [
        "Tidak mau? Oke tidak apa-apa!",
        "Nggak? Oke sayang, tidak apa-apa!",
        "Tidak! Wah pintar bilang tidak!",
        "Oke nggak mau, kita main lain!",
        "Tidak apa-apa! Coba yang lain!",
    ],
    "MAKAN": [
        "Makan! Yuk makan enak, ayo!",
        "Makan nasi! Wah enak ya!",
        "Mau makan? Pintar bilang makan!",
        "Makan! Ayo makan sama Mama!",
        "Makan enak! Nyam nyam, pintar!",
    ],
    "MINUM": [
        "Minum! Yuk minum air, ayo!",
        "Minum susu! Wah enak ya!",
        "Mau minum? Pintar bilang minum!",
        "Minum! Ayo minum sama Mama!",
        "Minum air! Ahhh segar, pintar!",
    ],
    "SUSU": [
        "Susu! Wah mau susu ya sayang!",
        "Susu enak! Yuk minum susu!",
        "Mau susu? Pintar bilang susu!",
        "Susu! Susu putih enak ya!",
        "Susu! Ayo minum susu, hebat!",
    ],

    # ── Melodic Jargon ───────────────────────────────────────
    "JARGON": [
        "Wah suara bagus! Coba bilang Mama!",
        "Bagus! Ayo coba bilang Papa!",
        "Suara lucu! Bilang Aaa yuk!",
        "Hehe bagus! Coba bilang Bola!",
        "Wah hebat! Yuk bilang Mama!",
    ],

    # ── Noise Fallback ───────────────────────────────────────
    "NOISE": [
        "Hmm, coba bilang Aaa!",
        "Yuk, bilang Ma-ma!",
        "Coba lagi ya sayang!",
        "Sini bilang Aaa sama Mama!",
        "Ayo coba bilang Pa-pa!",
    ],
}


def pick_template(phoneme: str) -> str:
    """Pick a random response template for the given phoneme."""
    pool = TEMPLATES.get(phoneme, TEMPLATES["NOISE"])
    return random.choice(pool)


def get_noise_fallback() -> str:
    """Get a gentle fallback response for unrecognized sounds."""
    return random.choice(TEMPLATES["NOISE"])
