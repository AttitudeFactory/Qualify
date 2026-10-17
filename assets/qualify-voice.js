/*
 * Qualify — voice notes for Conversaciones (QUA-226).
 *
 * Records the microphone through the Web Audio API and encodes a 16 kHz mono 16-bit WAV
 * in the browser — no codec involved, so it works in every browser and Instagram accepts
 * the result (`send-message.md`: audio aac/m4a/wav/mp4, ≤ 25 MB). The recording is handed
 * to the Reflex state in base64 parts under the websocket's 1 MB message limit:
 *
 *   window.qualifyVoice.start()  -> Promise<boolean>   (asks for the microphone)
 *   window.qualifyVoice.stop()   -> Promise<string>    JSON {seconds, bytes, parts}
 *   window.qualifyVoice.part(i)  -> string             JSON {index, data}
 *   window.qualifyVoice.cancel() -> void               (drops everything)
 *
 * The state drives the loop: `stop` answers how many parts there are, then one
 * `call_script("…part(i)")` per part, then `clear()`. `#q-voice-timer`, when present,
 * shows mm:ss while recording.
 */
(function () {
  "use strict";
  var TARGET_RATE = 16000;
  var MAX_SECONDS = 180;
  var PART_BYTES = 480 * 1024; // raw bytes per part → ~640 KB of base64

  var ctx = null, stream = null, source = null, proc = null, timer = null;
  var chunks = [], startedAt = 0, inputRate = 0, parts = [], seconds = 0, bytes = 0;

  function el() { return document.getElementById("q-voice-timer"); }

  function tick() {
    var node = el();
    if (!node) return;
    var s = Math.min(MAX_SECONDS, Math.floor((Date.now() - startedAt) / 1000));
    node.textContent = String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }

  function teardown() {
    if (timer) { clearInterval(timer); timer = null; }
    try { if (proc) { proc.disconnect(); proc.onaudioprocess = null; } } catch (e) {}
    try { if (source) source.disconnect(); } catch (e) {}
    try { if (stream) stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
    try { if (ctx) ctx.close(); } catch (e) {}
    ctx = null; stream = null; source = null; proc = null;
  }

  async function start() {
    if (ctx) return false;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return false;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      return false;
    }
    var AC = window.AudioContext || window.webkitAudioContext;
    ctx = new AC();
    inputRate = ctx.sampleRate;
    source = ctx.createMediaStreamSource(stream);
    proc = ctx.createScriptProcessor(4096, 1, 1);
    chunks = []; parts = []; seconds = 0; bytes = 0;
    startedAt = Date.now();
    proc.onaudioprocess = function (e) {
      if ((Date.now() - startedAt) / 1000 > MAX_SECONDS) return;
      chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    };
    source.connect(proc);
    proc.connect(ctx.destination);
    timer = setInterval(tick, 500);
    tick();
    return true;
  }

  function merge() {
    var n = 0;
    for (var i = 0; i < chunks.length; i++) n += chunks[i].length;
    var out = new Float32Array(n), off = 0;
    for (var j = 0; j < chunks.length; j++) { out.set(chunks[j], off); off += chunks[j].length; }
    return out;
  }

  function downsample(samples, from, to) {
    if (to >= from) return samples;
    var ratio = from / to;
    var length = Math.floor(samples.length / ratio);
    var out = new Float32Array(length);
    var pos = 0;
    for (var i = 0; i < length; i++) {
      var next = Math.floor((i + 1) * ratio);
      var sum = 0, count = 0;
      for (var k = pos; k < next && k < samples.length; k++) { sum += samples[k]; count++; }
      out[i] = count ? sum / count : 0;
      pos = next;
    }
    return out;
  }

  function wav(samples, rate) {
    var buffer = new ArrayBuffer(44 + samples.length * 2);
    var v = new DataView(buffer);
    function str(o, s) { for (var i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); }
    str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
    str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true);
    v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, samples.length * 2, true);
    var o = 44;
    for (var i = 0; i < samples.length; i++, o += 2) {
      var s = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Uint8Array(buffer);
  }

  function b64(bytesView) {
    var s = "";
    for (var i = 0; i < bytesView.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, bytesView.subarray(i, i + 0x8000));
    }
    return btoa(s);
  }

  async function stop() {
    if (!ctx) return JSON.stringify({ seconds: 0, bytes: 0, parts: 0 });
    var rate = inputRate;
    teardown();
    var samples = downsample(merge(), rate, TARGET_RATE);
    chunks = [];
    seconds = Math.round(samples.length / TARGET_RATE);
    var data = wav(samples, TARGET_RATE);
    bytes = data.length;
    parts = [];
    for (var i = 0; i < data.length; i += PART_BYTES) parts.push(b64(data.subarray(i, i + PART_BYTES)));
    return JSON.stringify({ seconds: seconds, bytes: bytes, parts: parts.length });
  }

  function part(i) {
    return JSON.stringify({ index: i, data: parts[i] || "" });
  }

  function clear() { parts = []; chunks = []; }

  function cancel() { teardown(); clear(); }

  window.qualifyVoice = { start: start, stop: stop, part: part, clear: clear, cancel: cancel };
})();
