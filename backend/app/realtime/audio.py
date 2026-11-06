"""PCM helpers. Audio on the wire is 16 kHz, mono, 16-bit little-endian PCM."""

import io
import math
import sys
import wave
from array import array

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2


def rms_dbfs(frame: bytes) -> float:
    """Loudness of a PCM16 frame in dBFS (0 = full scale, about -100 = digital silence)."""
    samples = array("h")
    samples.frombytes(frame[: len(frame) - len(frame) % 2])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return -100.0
    mean_sq = sum(s * s for s in samples) / len(samples)
    if mean_sq <= 0:
        return -100.0
    return 20 * math.log10(math.sqrt(mean_sq) / 32768)


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(BYTES_PER_SAMPLE)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def ms_to_bytes(ms: int, sample_rate: int = SAMPLE_RATE) -> int:
    return sample_rate * ms // 1000 * BYTES_PER_SAMPLE
