import math
import struct

RATE = 16000


def tone(ms: int, amplitude: int = 8000, freq: int = 220) -> bytes:
    n = RATE * ms // 1000
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * freq * i / RATE)))
        for i in range(n)
    )


def silence(ms: int) -> bytes:
    return b"\x00\x00" * (RATE * ms // 1000)


def chunks(pcm: bytes, ms: int = 100) -> list[bytes]:
    size = RATE * ms // 1000 * 2
    return [pcm[i : i + size] for i in range(0, len(pcm), size)]
