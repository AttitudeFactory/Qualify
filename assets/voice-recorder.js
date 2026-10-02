// Tu voz (§ request 2026-09-30): record the brand's voice from the microphone, right on
// ¿Cómo suena?. Plain DOM + MediaRecorder; Reflex drives it with `rx.call_script`
// (`VoiceLabState.start_recording` / `stop_recording`), whose callbacks get the string
// each function resolves to.
//
// Stopping does NOT upload anything itself: it builds a File from the recording and
// hands it to the block's own dropzone (`#brand_voice_sample`, `voice_lab.
// VOICE_UPLOAD_ID`) as if it had been picked — so a recording takes exactly the path
// an uploaded file does (`VoiceLabState.handle_sample_upload`): stored under the
// tenant's namespace, then Analizar / Clonar.
(function () {
  if (window.qualifyVoice) return;

  var MAX_SECONDS = 120; // what the analysis reads at most (`LocalWhisperTranscriptionProvider`)
  var recorder = null;
  var stream = null;
  var chunks = [];
  var startedAt = 0;
  var timer = null;

  function pickType() {
    var types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    for (var i = 0; i < types.length; i++) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(types[i])) return types[i];
    }
    return "";
  }

  function setClock(seconds) {
    var el = document.getElementById("q-voice-clock");
    if (el) {
      var s = Math.max(0, seconds);
      el.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
    }
  }

  function release() {
    if (timer) clearInterval(timer);
    timer = null;
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null;
  }

  function handOver(file) {
    var input = document.querySelector("#brand_voice_sample input[type=file]");
    if (!input) return "noinput";
    var transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    return "saved";
  }

  async function start() {
    if (recorder && recorder.state === "recording") return "recording";
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      return "unsupported";
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      return err && (err.name === "NotAllowedError" || err.name === "SecurityError")
        ? "denied"
        : "nomic";
    }
    chunks = [];
    var type = pickType();
    recorder = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
    recorder.ondataavailable = function (ev) {
      if (ev.data && ev.data.size) chunks.push(ev.data);
    };
    recorder.start(250);
    startedAt = Date.now();
    setClock(0);
    timer = setInterval(function () {
      var seconds = Math.floor((Date.now() - startedAt) / 1000);
      setClock(seconds);
      if (seconds >= MAX_SECONDS) stop(); // the dropzone's handler ends the recording state
    }, 250);
    return "recording";
  }

  function stop() {
    return new Promise(function (resolve) {
      if (!recorder || recorder.state === "inactive") {
        release();
        resolve("idle");
        return;
      }
      var current = recorder;
      current.onstop = function () {
        release();
        recorder = null;
        if (!chunks.length) {
          resolve("empty");
          return;
        }
        var type = current.mimeType || "audio/webm";
        var ext = type.indexOf("ogg") >= 0 ? "ogg" : type.indexOf("mp4") >= 0 ? "m4a" : "webm";
        var file = new File(chunks, "grabacion-" + Date.now() + "." + ext, { type: type.split(";")[0] });
        resolve(handOver(file));
      };
      current.stop();
    });
  }

  function cancel() {
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = null;
      recorder.stop();
    }
    recorder = null;
    chunks = [];
    release();
    return "idle";
  }

  window.qualifyVoice = { start: start, stop: stop, cancel: cancel };
})();
