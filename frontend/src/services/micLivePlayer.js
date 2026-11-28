import { openMicLive } from "./micApi";

// Plays one module's sound live.
//
// The backend sends the raw sound as the module makes it. The page
// turns it into small pieces of audio and plays them one after another.
// The sound is very quiet as sent, so it is made louder here, and
// "level" evens the volume out (quiet parts are lifted more than loud
// ones). Nothing here changes what is stored on the Pi.

const SAMPLE_RATE = 16000;

// Sound collected before playing starts, and again after a hiccup. It
// smooths out an uneven connection at the price of that much delay.
const PREBUFFER_SECONDS = 0.15;

// If playing has fallen further behind than this, the waiting sound is
// skipped so that live stays live.
const MAX_BEHIND_SECONDS = 0.8;


export function startMicLive(
  moduleId,
  { loudness, level, onLevel, onStop },
) {
  const AudioContextClass =
    window.AudioContext || window.webkitAudioContext;

  // Made inside the click that asked for it, or the browser keeps it
  // silent.
  const context = new AudioContextClass();
  context.resume();

  const gain = context.createGain();
  gain.gain.value = loudness;

  const compressor = context.createDynamicsCompressor();
  compressor.threshold.value = -40;
  compressor.knee.value = 30;
  compressor.ratio.value = 12;
  compressor.attack.value = 0.003;
  compressor.release.value = 0.25;

  function connect(useLevel) {
    gain.disconnect();
    compressor.disconnect();

    if (useLevel) {
      gain.connect(compressor);
      compressor.connect(context.destination);
    } else {
      gain.connect(context.destination);
    }
  }

  connect(level);

  const abort = new AbortController();
  let stopped = false;
  let playAt = 0;
  let oddByte = null;

  function finish(error) {
    if (stopped) {
      return;
    }

    stopped = true;
    abort.abort();
    context.close().catch(() => {});
    onStop(error || null);
  }

  function makeBuffer(samples) {
    try {
      const buffer = context.createBuffer(1, samples.length, SAMPLE_RATE);
      buffer.copyToChannel(samples, 0);
      return buffer;
    } catch {
      // A browser that refuses 16000 a second: give it three times as
      // many samples at 48000, each one repeated.
      const wide = new Float32Array(samples.length * 3);

      for (let index = 0; index < samples.length; index += 1) {
        wide[index * 3] = samples[index];
        wide[index * 3 + 1] = samples[index];
        wide[index * 3 + 2] = samples[index];
      }

      const buffer = context.createBuffer(1, wide.length, SAMPLE_RATE * 3);
      buffer.copyToChannel(wide, 0);
      return buffer;
    }
  }

  function play(bytes) {
    // A sample is two bytes; a piece from the network may end between
    // them. The odd one waits for the next piece.
    let data = bytes;

    if (oddByte !== null) {
      data = new Uint8Array(bytes.length + 1);
      data[0] = oddByte;
      data.set(bytes, 1);
      oddByte = null;
    }

    if (data.length % 2 === 1) {
      oddByte = data[data.length - 1];
      data = data.subarray(0, data.length - 1);
    }

    if (data.length === 0) {
      return;
    }

    const view = new DataView(data.buffer, data.byteOffset, data.length);
    const samples = new Float32Array(data.length / 2);
    let peak = 0;

    for (let index = 0; index < samples.length; index += 1) {
      const value = view.getInt16(index * 2, true);
      samples[index] = value / 32768;
      peak = Math.max(peak, Math.abs(value));
    }

    onLevel(peak);

    const now = context.currentTime;

    if (playAt < now + 0.02) {
      // Starting, or the sound ran out: collect a little first.
      playAt = now + PREBUFFER_SECONDS;
    } else if (playAt > now + MAX_BEHIND_SECONDS) {
      // Too far behind: skip what is waiting.
      playAt = now + PREBUFFER_SECONDS;
    }

    const source = context.createBufferSource();
    source.buffer = makeBuffer(samples);
    source.connect(gain);
    source.start(playAt);
    playAt += samples.length / SAMPLE_RATE;
  }

  async function run() {
    try {
      const response = await openMicLive(moduleId, abort.signal);
      const reader = response.body.getReader();

      while (!stopped) {
        const { value, done } = await reader.read();

        if (done) {
          break;
        }

        play(value);
      }

      finish(
        stopped
          ? null
          : new Error("The Pi ended the live sound."),
      );
    } catch (error) {
      finish(stopped ? null : error);
    }
  }

  run();

  return {
    stop() {
      finish(null);
    },
    setLoudness(value) {
      gain.gain.value = value;
    },
    setLevel(useLevel) {
      connect(useLevel);
    },
  };
}
