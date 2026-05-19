# SpeechLLM — Terapi Wicara AI 🇮🇩

AI-powered speech therapy assistant for Indonesian children aged 18–36 months.  
Detects babbling sounds and responds with therapeutically sound Indonesian phrases using **Expansion** and **Modeling** techniques.

## Architecture

```
🎤 Mic → [Silero VAD] → [Vosk STT] → [Phoneme Extractor]
                                              │
                                    [Semantic Router]
                                      │           │
                                   (70%)        (30%)
                                      │           │
                              [Templates]   [Gemini Flash-Lite]
                                      │           │
                                      └─── 🔊 Response ───┘
```

**Three-tier hybrid system:**
- **Tier 1**: Local sound detection (Silero VAD + Vosk + phoneme mapping)
- **Tier 2**: Deterministic semantic router (if/else → instant templates)
- **Tier 3**: Gemini 2.5 Flash-Lite for response variety (with validation filter)

## Quick Start

### 1. Prerequisites

- Python 3.11+
- macOS or Linux (Raspberry Pi supported for production)
- Microphone (for live mode)

### 2. Get a Gemini API Key (Free)

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account
3. Click **"Create API key"**
4. Copy the key — it starts with `AIza...`

> **Free tier**: Gemini 2.5 Flash-Lite offers generous free usage (1500 req/day).
> The system works without an API key too (template-only mode).

### 3. Clone & Setup

```bash
# Navigate to project
cd /Users/benedict/Projects/SpeechLLM

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and paste your GOOGLE_API_KEY
```

### 4. Download Models

```bash
# From the project root (SpeechLLM/):
python setup_models.py
```

This downloads:
- **Silero VAD** (~2MB) → `models/silero_vad.onnx`
- **Whisper tiny** (~75MB) → auto-cached in `~/.cache/huggingface/`

### 5. Run the Server

```bash
# IMPORTANT: Run from the project root, NOT from models/
cd /Users/benedict/Projects/SpeechLLM

uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Open API docs in browser
open http://localhost:8000/docs
```

### 6. Test It

```bash
# Health check
curl http://localhost:8000/health

# Test with simulated input
curl -X POST http://localhost:8000/process-text \
  -H "Content-Type: application/json" \
  -d '{"text": "ma"}'

# Expected response:
# {
#   "text": "Mama! Iya Mama di sini sayang!",
#   "source": "template",
#   "phoneme": "MA",
#   "intent_category": "syllable_modeling",
#   "technique": "modeling",
#   "latency_ms": 0.12,
#   "confidence": 0.9
# }

# Try more inputs
curl -X POST http://localhost:8000/process-text -H "Content-Type: application/json" -d '{"text": "a"}'
curl -X POST http://localhost:8000/process-text -H "Content-Type: application/json" -d '{"text": "susu"}'
curl -X POST http://localhost:8000/process-text -H "Content-Type: application/json" -d '{"text": "mau"}'
```

### 7. Run Tests

```bash
pytest tests/ -v
```

## Project Structure

```
SpeechLLM/
├── config.py                     # Central configuration
├── tier1_detector/               # Sound detection
│   ├── vad.py                    # Silero VAD (speech vs noise)
│   ├── recognizer.py             # Vosk Indonesian STT
│   └── phoneme_extractor.py      # Text → canonical phoneme
├── tier2_router/                 # Semantic routing
│   ├── intent_map.py             # Phoneme → TherapeuticIntent
│   ├── router.py                 # 70/30 template/Gemini split
│   └── templates.py              # 90+ pre-written responses
├── tier3_engine/                 # Gemini LLM
│   ├── prompts.py                # System prompt + few-shot examples
│   ├── gemini_client.py          # API client with timeout
│   └── response_filter.py       # Output validation
├── audio/                        # Audio I/O
│   ├── capture.py                # Mic capture
│   └── tts.py                    # Text-to-speech
├── api/                          # FastAPI
│   ├── main.py                   # App entry point
│   ├── routes.py                 # REST + WebSocket endpoints
│   └── schemas.py                # Request/response models
└── tests/                        # Test suite
```

## Speech Therapy Techniques

### Expansion (Ekspansi)
Take the child's sound and expand it into a real word with praise:
- Child: "a" → System: "Ayah! Wah pintar, coba bilang Ayah!"

### Modeling (Pemodelan)
Provide correct pronunciation example with enthusiastic tone:
- Child: "ma" → System: "Mama! Iya Mama di sini, pintar sekali!"

### Melodic Jargon Response
Redirect unintelligible babbling toward real words:
- Child: "lalala" → System: "Wah suara bagus! Coba bilang Mama!"

## Raspberry Pi Deployment Notes

For production deployment on Raspberry Pi:
1. Use the same Python setup (ARM64 wheels available for all dependencies)
2. Vosk small model runs well on RPi 4+ (50MB RAM footprint)
3. Silero VAD ONNX is CPU-optimized for ARM
4. Consider replacing gTTS with local `espeak` for offline TTS
5. Set `GEMINI_USAGE_PERCENT=0` for fully offline operation

## License

MIT
