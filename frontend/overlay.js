// Overlay para OBS/vMix (Browser Source). Uso:
//   http://localhost:8000/overlay.html?session=escenario-1&lang=es
//
// Sin controles ni fondo propio a propósito: se compone directo sobre el
// video real en el software de streaming. Se reconecta solo: puede cargarse
// antes de que arranque la sesión, y sigue funcionando si la sesión termina
// y vuelve a empezar con el mismo nombre (por ejemplo, entre charlas).

const params = new URLSearchParams(location.search);
const sessionId = params.get("session");
const lang = params.get("lang") || "original";

const box = document.getElementById("box");
const captionsEl = document.getElementById("captions");

const MIN_RETRY_MS = 2000;
let retryDelay = MIN_RETRY_MS;

function show(text) {
  if (!text) {
    box.hidden = true;
    return;
  }
  captionsEl.textContent = text;
  box.hidden = false;
}

function connect() {
  if (!sessionId) {
    console.warn("Falta ?session=<id> en la URL del overlay.");
    return;
  }

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(
    `${proto}://${location.host}/ws/captions/${encodeURIComponent(sessionId)}?lang=${encodeURIComponent(lang)}`
  );

  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.type === "caption") {
      retryDelay = MIN_RETRY_MS;
      show(data.text);
    } else {
      // "ended" o "error": se oculta y se reintenta al cerrarse.
      box.hidden = true;
    }
  };

  ws.onclose = () => {
    box.hidden = true;
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 1.5, 5000);
  };
}

connect();
