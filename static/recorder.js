/** Encode raw mono samples as the PCM WAV format Azure accepts. */
export function encodeWav(samples, rate = 16000) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset, text) => [...text].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
  write(0, "RIFF");
  view.setUint32(4, buffer.byteLength - 8, true);
  write(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((value, index) => {
    const sample = Math.max(-1, Math.min(1, value));
    view.setInt16(44 + index * 2, Math.round(sample * (sample < 0 ? 0x8000 : 0x7fff)), true);
  });
  return new Blob([buffer], { type: "audio/wav" });
}

export class PCMRecorder {
  /** Start only after a user gesture and release the microphone on every exit. */
  async start(onLimit) {
    this.chunks = [];
    this.finished = false;
    this.stopping = null;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      this.context = new AudioContext();
      await this.context.resume();
      await this.context.audioWorklet.addModule(new URL("./recorder-worklet.js", import.meta.url));
      this.source = this.context.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.context, "library-recorder", {
        processorOptions: { maxFrames: Math.floor(this.context.sampleRate * 30) },
      });
      this.node.port.onmessage = ({ data }) => {
        if (data.samples) this.chunks.push(data.samples);
        if (data.stopped) {
          this.finished = true;
          this.resolveStop?.();
          if (data.reason === "limit") onLimit();
        }
      };
      this.silent = this.context.createGain();
      this.silent.gain.value = 0;
      this.source.connect(this.node).connect(this.silent).connect(this.context.destination);
    } catch (error) {
      await this.release();
      throw error;
    }
  }

  stop(discard = false) {
    if (!this.stopping) this.stopping = this.finish(discard);
    return this.stopping;
  }

  async finish(discard) {
    try {
      if (!this.finished) {
        await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error("Recording stopped unexpectedly. Please record again.")), 2000);
          this.resolveStop = () => { clearTimeout(timeout); resolve(); };
          this.node.port.postMessage("stop");
        });
      }
      const rate = this.context.sampleRate;
      await this.release();
      if (discard) return null;
      const length = this.chunks.reduce((sum, chunk) => sum + chunk.length, 0);
      if (length < rate / 10) throw new Error("Record at least a moment of speech before stopping.");
      const pcm = new Float32Array(length);
      let offset = 0;
      for (const chunk of this.chunks) { pcm.set(chunk, offset); offset += chunk.length; }
      // Browsers commonly capture at 44.1/48 kHz. Resample before WAV encoding.
      const offline = new OfflineAudioContext(1, Math.min(480000, Math.round(length * 16000 / rate)), 16000);
      const input = offline.createBuffer(1, length, rate);
      input.copyToChannel(pcm, 0);
      const source = offline.createBufferSource();
      source.buffer = input;
      source.connect(offline.destination);
      source.start();
      const rendered = await offline.startRendering();
      return encodeWav(rendered.getChannelData(0));
    } finally {
      this.chunks = [];
      await this.release();
    }
  }

  async release() {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.source?.disconnect();
    this.node?.disconnect();
    this.silent?.disconnect();
    if (this.context && this.context.state !== "closed") await this.context.close();
  }
}
