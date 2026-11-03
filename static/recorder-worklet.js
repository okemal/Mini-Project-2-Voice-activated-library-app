/** Collect bounded mono PCM inside the audio thread; never send network data. */
class LibraryRecorder extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.buffer = new Float32Array(4096);
    this.used = 0;
    this.frames = 0;
    this.maxFrames = options.processorOptions.maxFrames;
    this.recording = true;
    this.port.onmessage = () => this.stop("user");
  }

  flush() {
    if (!this.used) return;
    const samples = this.buffer.slice(0, this.used);
    this.port.postMessage({ samples }, [samples.buffer]);
    this.used = 0;
  }

  stop(reason) {
    this.recording = false;
    this.flush();
    this.port.postMessage({ stopped: true, reason });
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!this.recording || !input) return true;
    for (let index = 0; index < input.length; index += 1) {
      this.buffer[this.used++] = input[index];
      this.frames += 1;
      if (this.used === this.buffer.length) this.flush();
      if (this.frames >= this.maxFrames) {
        this.stop("limit");
        break;
      }
    }
    return true;
  }
}

registerProcessor("library-recorder", LibraryRecorder);
