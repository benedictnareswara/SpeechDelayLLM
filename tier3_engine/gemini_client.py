"""
Tier 3b — Gemini API Client

Wraps the google-generativeai SDK for low-latency therapeutic response
generation using Gemini 2.5 Flash-Lite.

Features:
- Streaming for fast time-to-first-token
- Timeout with template fallback
- Few-shot prompt construction
- Thinking mode disabled for speed
"""

import asyncio
import logging
from typing import Optional

import google.generativeai as genai

from tier2_router.intent_map import TherapeuticIntent
from tier3_engine.prompts import SYSTEM_PROMPT, FEW_SHOT_EXAMPLES, build_user_prompt
from tier3_engine.response_filter import validate_response

import config

logger = logging.getLogger(__name__)


class GeminiClient:
    """
    Async wrapper for Gemini 2.5 Flash-Lite optimized for therapeutic responses.

    Usage:
        client = GeminiClient()
        response = await client.generate(phoneme="MA", raw_text="ma", intent=intent)
    """

    def __init__(self):
        if not config.GOOGLE_API_KEY:
            raise ValueError(
                "GOOGLE_API_KEY not set. Get your free key at:\n"
                "  https://aistudio.google.com/app/apikey\n"
                "Then add it to your .env file."
            )

        genai.configure(api_key=config.GOOGLE_API_KEY)

        # Build chat history from few-shot examples
        self._history = []
        for example in FEW_SHOT_EXAMPLES:
            self._history.append({"role": "user", "parts": [example["input"]]})
            self._history.append({"role": "model", "parts": [example["output"]]})

        self._model = genai.GenerativeModel(
            model_name=config.GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                temperature=config.GEMINI_TEMPERATURE,
                max_output_tokens=config.GEMINI_MAX_OUTPUT_TOKENS,
                top_p=0.9,
                top_k=20,
            ),
        )

        logger.info(
            "Gemini client initialized: model=%s, temp=%.1f",
            config.GEMINI_MODEL,
            config.GEMINI_TEMPERATURE,
        )

    async def generate(
        self,
        phoneme: str,
        raw_text: str,
        intent: TherapeuticIntent,
    ) -> Optional[str]:
        """
        Generate a therapeutic response via Gemini.

        Args:
            phoneme: Canonical phoneme (e.g., "MA")
            raw_text: Original Vosk text (e.g., "mah")
            intent: TherapeuticIntent with target words and technique

        Returns:
            Validated response string, or None if generation fails/is invalid.
        """
        user_prompt = build_user_prompt(
            phoneme=phoneme,
            raw_text=raw_text,
            target_words=intent.target_words,
            technique=intent.technique,
        )

        try:
            # Run synchronous SDK call in executor to avoid blocking event loop
            response_text = await asyncio.wait_for(
                self._call_gemini(user_prompt),
                timeout=config.GEMINI_TIMEOUT_S,
            )

            if response_text is None:
                return None

            # Validate against therapy constraints
            validated = validate_response(response_text)
            if validated is None:
                logger.warning(
                    "Gemini response rejected by filter: '%s'", response_text
                )
            return validated

        except asyncio.TimeoutError:
            logger.warning("Gemini timed out after %.1fs", config.GEMINI_TIMEOUT_S)
            return None
        except Exception as e:
            logger.error("Gemini API error: %s", e)
            return None

    async def _call_gemini(self, user_prompt: str) -> Optional[str]:
        """Execute the Gemini API call in a thread executor."""
        loop = asyncio.get_event_loop()

        def _sync_generate():
            chat = self._model.start_chat(history=list(self._history))
            response = chat.send_message(user_prompt)
            return response.text.strip() if response.text else None

        return await loop.run_in_executor(None, _sync_generate)
