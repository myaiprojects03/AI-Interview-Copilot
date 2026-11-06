"""Replay a recorded interview through the live copilot WebSocket, in real time.

Streams a 16 kHz mono 16-bit WAV as the interviewer channel and prints transcripts,
suggestions and per-turn timings. The backend must be running.

Run from backend/:
    python -m scripts.replay_interview
    python -m scripts.replay_interview path/to/interview.wav --speed 2
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
import wave
from pathlib import Path

from websockets.asyncio.client import connect

DEFAULT_WAV = Path(__file__).resolve().parents[2] / "frontend/public/demo/mock-interview.wav"
CHUNK_MS = 100


def load_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            sys.exit(f"{path} must be 16 kHz mono 16-bit PCM")
        return w.readframes(w.getnframes())


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", nargs="?", type=Path, default=DEFAULT_WAV)
    parser.add_argument("--url", default="ws://localhost:8000/ws/session")
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed multiplier")
    parser.add_argument("--session-type", default="mixed")
    args = parser.parse_args()

    pcm = load_pcm(args.wav)
    size = 16000 * CHUNK_MS // 1000 * 2
    timings: list[dict] = []
    answers: dict[int, str] = {}

    async with connect(args.url, max_size=None) as ws:
        first = json.loads(await ws.recv())
        if first["type"] != "ready":
            print("Server error:", first.get("message"))
            return 1
        await ws.send(json.dumps({"type": "start", "session_type": args.session_type}))

        async def send_audio() -> None:
            start = time.monotonic()
            for i in range(0, len(pcm), size):
                await ws.send(b"\x00" + pcm[i : i + size])
                due = start + (i // size + 1) * CHUNK_MS / 1000 / args.speed
                await asyncio.sleep(max(0, due - time.monotonic()))
            # Trailing silence so the last utterance is endpointed, then wait for answers.
            for _ in range(15):
                await ws.send(b"\x00" + b"\x00\x00" * (size // 2))
                await asyncio.sleep(CHUNK_MS / 1000)
            await asyncio.sleep(6)

        sender = asyncio.create_task(send_audio())
        try:
            while not sender.done():
                try:
                    event = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.5))
                except TimeoutError:
                    continue
                kind = event["type"]
                if kind == "transcript" and event["final"]:
                    print(f"\n[{event['channel']}] {event['text']}  (STT {event['stt_ms']} ms)")
                elif kind == "suggestion_start":
                    answers[event["id"]] = ""
                    print(f"\n--- suggestion #{event['id']} ---")
                elif kind == "suggestion_delta":
                    answers[event["id"]] += event["text"]
                    print(event["text"], end="", flush=True)
                elif kind == "suggestion_end":
                    t = event["timings"]
                    print(f"\n--- {event['status']}: {t}")
                    if event["status"] == "done":
                        timings.append(t)
                elif kind == "error":
                    print(f"\n!! {event['message']}")
        finally:
            sender.cancel()

    if timings:
        def summary(key: str) -> str:
            values = [t[key] for t in timings if key in t]
            if not values:
                return "n/a"
            return f"median {statistics.median(values):.0f} ms, max {max(values)} ms"

        print("\n==== Summary ====")
        print(f"answers:                         {len(timings)}")
        print(f"question end -> first words:     {summary('speech_end_to_first_token_ms')}")
        print(f"speech-to-text (final):          {summary('stt_ms')}")
        print(f"LLM first token:                 {summary('llm_first_token_ms')}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
