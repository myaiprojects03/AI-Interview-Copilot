"""Check that the free-tier provider keys in .env actually work.

Run from backend/:  python -m scripts.smoke_check
"""

import asyncio
import io
import math
import struct
import sys
import time
import wave

from app.core.config import get_settings
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import get_llm, get_stt


def _tone_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(
            b"".join(
                struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / rate)))
                for i in range(int(seconds * rate))
            )
        )
    return buf.getvalue()


async def main() -> int:
    settings = get_settings()
    ok = True

    print(f"LLM ({settings.llm_provider}) ...", end=" ", flush=True)
    try:
        llm = get_llm(settings)
        start = time.perf_counter()
        first_token_ms = None
        text = ""
        async for part in llm.stream_chat(
            [ChatMessage("user", "Reply with exactly: copilot ready")], max_tokens=200
        ):
            if first_token_ms is None:
                first_token_ms = (time.perf_counter() - start) * 1000
            text += part
        print(f"OK  first token {first_token_ms:.0f} ms  reply={text.strip()!r}")
    except ProviderError as exc:
        ok = False
        print(f"FAILED  {exc}")

    print(f"STT ({settings.stt_provider}) ...", end=" ", flush=True)
    try:
        stt = get_stt(settings)
        start = time.perf_counter()
        result = await stt.transcribe(_tone_wav(), filename="tone.wav")
        ms = (time.perf_counter() - start) * 1000
        print(f"OK  {ms:.0f} ms  (test tone, so empty or odd text is normal: {result.text!r})")
    except ProviderError as exc:
        ok = False
        print(f"FAILED  {exc}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
