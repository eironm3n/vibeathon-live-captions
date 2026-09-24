// Overlay para OBS/vMix (Browser Source). Uso:
//   http://localhost:8000/overlay.html?session=escenario-1&lang=es
//
// Sin controles ni fondo propio a propósito: se compone directo sobre el
// video real en el software de streaming.

const params = new URLSearchParams(location.search);
const sessionId = params.get("session");
const lang = params.get("lang") || "original";

const box = document.getElementById("box");
const captionsEl = document.getElementById("captions");

let ws = null;
let retryDelay = 2000;

function show(text, interim) {
  if (!text) {
    box.hidden = true;
    return;
  }
  captionsEl.textContent = text;
  captionsEl.classList.toggle("interim", Boolean(interim));
  box.hidden = false;
}

function connect() {
  if (!sessionId) {
    console.warn("Falta ?session=<id> en la URL del overlay.");
    return;
  }

  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/captions/${sessionId}?lang=${lang}`);

  ws.onopen = () => {
    retryDelay = 2000;
  };

  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.error) {
      box.hidden = true;
      return;
    }
    show(data.text, !data.is_final);
  };

  ws.onclose = () => {
    // La sesión puede no existir todavía (el overlay se carga antes de que
    // arranque el audio) o haber terminado: reintentamos solos.
    box.hidden = true;
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 1.5, 15000);
  };
}

connect();
