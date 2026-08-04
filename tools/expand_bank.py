#!/usr/bin/env python3
"""
Draft new phrase variants with Gemini, for a human to review.

This is the *only* role Gemini plays in the shipped system. It runs on your
laptop, writes nothing automatically, and every line it proposes is printed for
you to accept or reject before it can ever reach a child.

    python tools/expand_bank.py --phoneme MA --count 5
    python tools/expand_bank.py --all --count 3 --out drafts.txt

Nothing is written to templates.py. Copy the lines you approve in yourself —
that manual step is deliberate. These phrases are spoken to toddlers in a
therapeutic context, and an unreviewed generated line has no business in the
bank. After editing templates.py, re-run tools/render_bank.py and re-burn the
card.

Every draft is passed through the same response filter the runtime uses, so
lines that are too long, too complex, or off-persona are rejected before you
even see them.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "speechllm-core" / "src"))

from speechllm_core.generation.response_filter import validate_response  # noqa: E402
from speechllm_core.routing.intents import INTENT_REGISTRY, get_intent  # noqa: E402
from speechllm_core.routing.templates import TEMPLATES  # noqa: E402
from speechllm_core.settings import settings  # noqa: E402


async def draft_for(client, phoneme: str, count: int) -> list[str]:
    """Generate `count` candidate phrases for one phoneme, filtered and deduped."""
    intent = get_intent(phoneme)
    existing = set(TEMPLATES.get(phoneme, []))
    drafts: list[str] = []
    seen = set(existing)

    # Over-request: the filter and dedupe both reject a fair share.
    for _ in range(count * 3):
        if len(drafts) >= count:
            break
        try:
            text = await client.generate(
                phoneme=phoneme,
                raw_text=phoneme.lower(),
                intent=intent,
            )
        except Exception as e:  # noqa: BLE001
            print(f"    ! generation error: {e}")
            break
        if not text:
            continue
        # client.generate already filters, but re-check explicitly: this script
        # is the gate for content that gets rendered to audio.
        cleaned = validate_response(text)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            drafts.append(cleaned)

    return drafts


async def run(phonemes: list[str], count: int, out: Path | None) -> int:
    if not settings.google_api_key:
        print("GOOGLE_API_KEY is not set. Add it to .env — see .env.example.")
        return 1

    from speechllm_core.generation.gemini_client import GeminiClient

    client = GeminiClient()
    lines: list[str] = []

    for phoneme in phonemes:
        intent = get_intent(phoneme)
        print(f"\n── {phoneme} ({intent.category}, {intent.technique}) ──")
        print(f"   existing: {len(TEMPLATES.get(phoneme, []))} phrases")
        drafts = await draft_for(client, phoneme, count)
        if not drafts:
            print("   no usable drafts (all rejected by the filter)")
            continue
        lines.append(f'    # ── drafts for {phoneme} — REVIEW BEFORE USE ──')
        for text in drafts:
            print(f'   + "{text}"')
            lines.append(f'    "{text}",')

    if out and lines:
        out.write_text("\n".join(lines) + "\n")
        print(f"\nWrote {len(lines)} lines to {out}")

    print(
        "\n⚠️  Nothing was added to templates.py. Review each line, paste the ones you\n"
        "   approve into routing/templates.py, then re-run tools/render_bank.py."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft phrase variants for human review")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--phoneme", help="single phoneme, e.g. MA")
    group.add_argument("--all", action="store_true", help="every phoneme in the registry")
    parser.add_argument("--count", type=int, default=3, help="drafts per phoneme")
    parser.add_argument("--out", type=Path, default=None, help="also write to a file")
    args = parser.parse_args(argv)

    if args.all:
        phonemes = [p for p in sorted(INTENT_REGISTRY) if p != "NOISE"]
    else:
        phoneme = args.phoneme.upper()
        if phoneme not in INTENT_REGISTRY:
            print(f"Unknown phoneme {phoneme!r}. Known: {', '.join(sorted(INTENT_REGISTRY))}")
            return 1
        phonemes = [phoneme]

    return asyncio.run(run(phonemes, args.count, args.out))


if __name__ == "__main__":
    raise SystemExit(main())
