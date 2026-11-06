/** Browser audio capture: meeting tab audio + microphone, as 16 kHz mono PCM16 chunks. */

export type CaptureHandle = { stop: () => void };

export async function captureStream(
  stream: MediaStream,
  onChunk: (pcm: ArrayBuffer, rms: number) => void,
): Promise<CaptureHandle> {
  const ctx = new AudioContext({ sampleRate: 16000 });
  await ctx.audioWorklet.addModule("/pcm-worklet.js");
  const source = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, "pcm-capture");
  // The worklet only runs while connected to the output; a zero gain keeps it silent.
  const mute = ctx.createGain();
  mute.gain.value = 0;
  source.connect(node).connect(mute).connect(ctx.destination);
  node.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; rms: number }>) =>
    onChunk(e.data.pcm, e.data.rms);
  if (ctx.state === "suspended") await ctx.resume();
  return {
    stop: () => {
      node.port.onmessage = null;
      source.disconnect();
      node.disconnect();
      void ctx.close();
    },
  };
}

/** Ask the user to share the meeting tab, with its audio. Chrome and Edge only. */
export async function getTabAudio(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new Error("This browser can't capture tab audio. Use Chrome or Edge on a laptop.");
  }
  const options = {
    video: true, // Chrome requires video to offer tab audio; the video track is stopped below.
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    preferCurrentTab: false,
    selfBrowserSurface: "exclude",
    systemAudio: "include",
  } as DisplayMediaStreamOptions;
  const stream = await navigator.mediaDevices.getDisplayMedia(options);
  const audio = stream.getAudioTracks();
  stream.getVideoTracks().forEach((t) => t.stop());
  if (audio.length === 0) {
    throw new Error(
      'No audio was shared. Choose the meeting\'s browser tab and turn on "Share tab audio".',
    );
  }
  return new MediaStream(audio);
}

export async function getMic(): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
}

export function stopStream(stream: MediaStream | null | undefined) {
  stream?.getTracks().forEach((t) => t.stop());
}
