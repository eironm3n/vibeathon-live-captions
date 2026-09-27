// Panel para emitir audio a una sesión desde el navegador: micrófono en
// vivo, o un archivo que se decodifica, se baja a 16 kHz mono y se transmite
// a ritmo real (igual que tools/stream_audio_file.py, sin terminal ni ffmpeg).

const SAMPLE_RATE = 16000;
const CHUNK_MS = 100;
const TOKEN_KEY = "opencaption.ingestToken";
const LANGUAGES = ["es", "en", "pt", "fr", "de", "it"];

const CLOSE_MESSAGES = {
  4400: "El servidor rechazó el pedido (revisá el nombre de la sesión y los idiomas).",
  4401: "Token inválido.",
  4409: "Ya hay otro emisor conectado a esa sesión. Elegí otro nombre.",
  4429: "El servidor alcanzó el máximo de sesiones simultáneas.",
};

const form = document.getElementById("form");
const tokenInput = document.getElementById("token");
const sessionInput = document.getElementById("session-id");
const sourceLangSelect = document.getElementById("source-lang");
const targetLangSelect = document.getElementById("target-lang");
const fileBlock = document.getElementById("file-block");
const fileInput = document.getElementById("file");
const dropzone = document.getElementById("dropzone");
const filenameEl = document.getElementById("filename");
const startBtn = document.getElementById("start");
const progressEl = document.getElementById("progress");
const statusEl = document.getElementById("status");
const openLinks = document.getElementById("open-links");
const overlayLink = document.getElementById("overlay-link");

let selectedFile = null;
// Emisión en curso: { ws, stop() } o null.
let active = null;

// --- Formulario ---------------------------------------------------------

function fillLanguages(select, codes, selected) {
  select.replaceChildren();
  codes.forEach((code) => {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = code === "auto" ? "Detectar automáticamente" : languageLabel(code);
    opt.selected = code === selected;
    select.appendChild(opt);
  });
}

async function loadDefaults() {
  let config = { source_lang: "en", target_lang: "es" };
  try {
    config = await (await fetch("/api/config")).json();
  } catch {
    // Sin config seguimos con los valores por defecto.
  }
  fillLanguages(sourceLangSelect, ["auto", ...LANGUAGES], config.source_lang);
  fillLanguages(targetLangSelect, LANGUAGES, config.target_lang);
}

function sourceMode() {
  return form.querySelector('input[name="source"]:checked').value;
}

function setFile(file) {
  selectedFile = file;
  filenameEl.textContent = file ? file.name : "";
}

function setBusy(busy) {
  startBtn.textContent = busy ? "Detener" : "Iniciar transmisión";
  startBtn.classList.toggle("stop", busy);
  form.querySelectorAll("input, select").forEach((el) => (el.disabled = busy));
}

try {
  tokenInput.value = sessionStorage.getItem(TOKEN_KEY) || "";
} catch {
  // sessionStorage bloqueado: el token se pide cada vez.
}
sessionInput.value = "sesion-" + Math.random().toString(36).slice(2, 8);
sessionInput.addEventListener("input", () => {
  sessionInput.value = sessionInput.value.toLowerCase().replace(/\s+/g, "-");
});

form.querySelectorAll('input[name="source"]').forEach((radio) =>
  radio.addEventListener("change", () => {
    fileBlock.hidden = sourceMode() !== "file";
  })
);

fileInput.addEventListener("change", () => setFile(fileInput.files[0] || null));
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" || ev.key === " ") {
    ev.preventDefault();
    fileInput.click();
  }
});
dropzone.addEventListener("dragover", (ev) => {
  ev.preventDefault();
  dropzone.classList.add("drag");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag"));
dropzone.addEventListener("drop", (ev) => {
  ev.preventDefault();
  dropzone.classList.remove("drag");
  const file = ev.dataTransfer.files[0];
  if (file) setFile(file);
});

// --- Conexión con el backend ----------------------------------------------

// Abre la ingesta, se autentica y resuelve cuando el servidor confirma.
function openIngest(sessionId) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/ingest/${encodeURIComponent(sessionId)}`);
  ws.binaryType = "arraybuffer";

  return new Promise((resolve, reject) => {
    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          token: tokenInput.value.trim(),
          source_lang: sourceLangSelect.value,
          target_lang: targetLangSelect.value,
        })
      );
    };
    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      if (data.type === "ready") resolve(ws);
    };
    ws.onclose = (ev) => {
      reject(new Error(CLOSE_MESSAGES[ev.code] || ev.reason || "No se pudo conectar al servidor."));
    };
  });
}

function watchClose(ws, onUnexpectedClose) {
  ws.onclose = (ev) => {
    if (active && active.ws === ws) onUnexpectedClose(CLOSE_MESSAGES[ev.code] || ev.reason || "Se cortó la conexión.");
  };
}

// --- Micrófono ----------------------------------------------------------

async function startMicrophone(ws) {
  if (!navigator.mediaDevices || !window.isSecureContext) {
    throw new Error("El micrófono solo funciona en https:// o en localhost.");
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: false, noiseSuppression: true, autoGainControl: true },
  });
  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule("mic-worklet.js");
  const source = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, "pcm16-downsampler", { numberOfOutputs: 0 });
  node.port.onmessage = (ev) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(ev.data);
  };
  source.connect(node);

  return () => {
    node.port.onmessage = null;
    source.disconnect();
    stream.getTracks().forEach((track) => track.stop());
    ctx.close();
  };
}

// --- Archivo --------------------------------------------------------------

async function decodeAndResample(file) {
  const arrayBuffer = await file.arrayBuffer();
  const probeCtx = new AudioContext();
  const decoded = await probeCtx.decodeAudioData(arrayBuffer);
  await probeCtx.close();

  const offlineCtx = new OfflineAudioContext(1, Math.ceil(decoded.duration * SAMPLE_RATE), SAMPLE_RATE);
  const source = offlineCtx.createBufferSource();
  source.buffer = decoded;
  source.connect(offlineCtx.destination);
  source.start();
  const rendered = await offlineCtx.startRendering();
  return rendered.getChannelData(0); // Float32Array mono a 16kHz
}

function floatTo16BitPCM(float32) {
  const int16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return int16;
}

// Transmite a ritmo real guiándose por el reloj, no por la cantidad de
// setTimeout: si la pestaña queda en segundo plano el navegador espacia los
// timers (hasta 1 por segundo) y acá simplemente se envía lo atrasado.
async function streamFile(ws, pcm16, isStopped) {
  const samplesPerChunk = (SAMPLE_RATE * CHUNK_MS) / 1000;
  const startedAt = performance.now();
  let sent = 0;
  while (sent < pcm16.length && !isStopped()) {
    if (ws.readyState !== WebSocket.OPEN) return;
    const due = Math.min(pcm16.length, ((performance.now() - startedAt) / 1000) * SAMPLE_RATE + samplesPerChunk);
    while (sent < due) {
      ws.send(pcm16.slice(sent, sent + samplesPerChunk).buffer);
      sent += samplesPerChunk;
    }
    progressEl.value = Math.round((Math.min(sent, pcm16.length) / pcm16.length) * 100);
    await new Promise((r) => setTimeout(r, CHUNK_MS));
  }
}

// --- Inicio / fin -----------------------------------------------------------

function finish(message) {
  if (active) {
    const { ws, stop } = active;
    active = null;
    stop();
    ws.close();
  }
  setBusy(false);
  startBtn.disabled = false;
  progressEl.hidden = true;
  statusEl.textContent = message;
}

async function start() {
  const sessionId = sessionInput.value.trim();
  const mode = sourceMode();
  if (mode === "file" && !selectedFile) {
    statusEl.textContent = "Elegí un archivo primero.";
    return;
  }
  try {
    sessionStorage.setItem(TOKEN_KEY, tokenInput.value.trim());
  } catch {
    // Ver arriba.
  }

  setBusy(true);
  // Hasta que la emisión arranque, el botón no hace nada (evita dobles inicios).
  startBtn.disabled = true;
  openLinks.style.display = "none";
  let pcm = null;
  try {
    if (mode === "file") {
      statusEl.textContent = "Procesando el archivo (puede tardar unos segundos)...";
      pcm = floatTo16BitPCM(await decodeAndResample(selectedFile));
    }
    statusEl.textContent = "Conectando...";
    const ws = await openIngest(sessionId);
    let stopped = false;
    active = { ws, stop: () => (stopped = true) };
    startBtn.disabled = false;
    watchClose(ws, (message) => finish(`Transmisión interrumpida: ${message}`));

    overlayLink.href = `overlay.html?session=${encodeURIComponent(sessionId)}&lang=${encodeURIComponent(targetLangSelect.value)}`;
    openLinks.style.display = "flex";

    if (mode === "mic") {
      const stopMic = await startMicrophone(ws);
      active.stop = stopMic;
      statusEl.textContent = `En vivo: transmitiendo el micrófono a "${sessionId}".`;
    } else {
      progressEl.hidden = false;
      progressEl.value = 0;
      statusEl.textContent = `Transmitiendo "${selectedFile.name}" a "${sessionId}"...`;
      await streamFile(ws, pcm, () => stopped);
      if (active && active.ws === ws) finish(`Listo: archivo transmitido completo a "${sessionId}".`);
    }
  } catch (err) {
    console.error(err);
    finish("Error: " + err.message);
  }
}

form.addEventListener("submit", (ev) => {
  ev.preventDefault();
  if (active) finish("Transmisión detenida.");
  else start();
});

loadDefaults();
