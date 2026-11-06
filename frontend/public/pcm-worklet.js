// Runs on the audio thread. The AudioContext runs at 16 kHz, so the browser has already
// resampled. This mixes to mono, converts to 16-bit PCM and posts 100 ms chunks.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.size = 1600; // 100 ms at 16 kHz
    this.buf = new Int16Array(this.size);
    this.n = 0;
    this.sumSq = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channels = input.length;
    const frames = input[0].length;
    for (let i = 0; i < frames; i++) {
      let s = 0;
      for (let c = 0; c < channels; c++) s += input[c][i];
      s = Math.max(-1, Math.min(1, s / channels));
      this.sumSq += s * s;
      this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.n === this.size) {
        const rms = Math.sqrt(this.sumSq / this.size);
        this.port.postMessage({ pcm: this.buf.buffer, rms }, [this.buf.buffer]);
        this.buf = new Int16Array(this.size);
        this.n = 0;
        this.sumSq = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
