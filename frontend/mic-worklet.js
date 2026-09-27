// AudioWorklet: baja el audio del micrófono (44.1/48 kHz, float) a PCM16
// mono 16 kHz y lo entrega en bloques de 100 ms al hilo principal.
//
// Cada muestra de salida es el promedio de las de entrada que le
// corresponden: un filtro pasa-bajos simple que reduce el aliasing al
// bajar la frecuencia de muestreo (suficiente para voz).

const TARGET_RATE = 16000;
const BLOCK_SAMPLES = TARGET_RATE / 10;

class Pcm16Downsampler extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
    this.position = 0;
    this.sum = 0;
    this.count = 0;
    this.block = new Int16Array(BLOCK_SAMPLES);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      this.sum += channel[i];
      this.count++;
      this.position += 1;
      if (this.position < this.ratio) continue;

      this.position -= this.ratio;
      const sample = Math.max(-1, Math.min(1, this.sum / this.count));
      this.block[this.filled++] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      this.sum = 0;
      this.count = 0;

      if (this.filled === BLOCK_SAMPLES) {
        this.port.postMessage(this.block.buffer, [this.block.buffer]);
        this.block = new Int16Array(BLOCK_SAMPLES);
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm16-downsampler", Pcm16Downsampler);
