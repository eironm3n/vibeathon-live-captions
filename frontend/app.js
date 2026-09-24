const sessionSelect = document.getElementById("session");
const langButtons = document.querySelectorAll(".lang-btn");
const captionsEl = document.getElementById("captions");
const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("status-text");
const overlayLink = document.getElementById("overlay-link");
const srtLink = document.getElementById("srt-link");
const vttLink = document.getElementById("vtt-link");

let ws = null;
let currentLang = "original";

function updateLinks() {
  const sessionId = sessionSelect.value;
  const links = [overlayLink, srtLink, vttLink];
  if (!sessionId) {
    links.forEach((a) => a.classList.add("disabled"));
    return;
  }
  links.forEach((a) => a.classList.remove("disabled"));
  overlayLink.href = `overlay.html?session=${encodeURIComponent(sessionId)}&lang=${currentLang}`;
  srtLink.href = `/api/sessions/${encodeURIComponent(sessionId)}/export?lang=${currentLang}&fmt=srt`;
  vttLink.href = `/api/sessions/${encodeURIComponent(sessionId)}/export?lang=${currentLang}&fmt=vtt`;
}

function setStatus(text, live) {
  statusTextEl.textContent = text;
  statusEl.classList.toggle("live", Boolean(live));
}

function setCaptions(text, { interim = false, placeholder = false } = {}) {
  captionsEl.textContent = text;
  captionsEl.classList.toggle("interim", interim);
  captionsEl.classList.toggle("placeholder", placeholder);
  // Reinicia la animación de entrada en cada actualización.
  captionsEl.style.animation = "none";
  void captionsEl.offsetWidth;
  captionsEl.style.animation = "";
}

async function refreshSessions() {
  const res = await fetch("/api/sessions");
  const data = await res.json();
  const previous = sessionSelect.value;

  sessionSelect.innerHTML = "";
  if (data.sessions.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "Sin sesiones activas";
    opt.disabled = true;
    opt.selected = true;
    sessionSelect.appendChild(opt);
    if (ws) {
      ws.close();
      ws = null;
    }
    setStatus("desconectado", false);
    setCaptions("Elegí una sesión para empezar.", { placeholder: true });
    updateLinks();
    return;
  }

  data.sessions.forEach((id) => {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = id;
    sessionSelect.appendChild(opt);
  });

  if (data.sessions.includes(previous)) {
    sessionSelect.value = previous;
  } else {
    connect();
  }
}

function connect() {
  const sessionId = sessionSelect.value;
  if (!sessionId) return;

  if (ws) ws.close();
  updateLinks();

  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/captions/${sessionId}?lang=${currentLang}`);

  setStatus("conectando...", false);
  setCaptions("Esperando audio...", { placeholder: true });

  ws.onopen = () => {
    setStatus(`en vivo · ${sessionId} · ${currentLang}`, true);
  };

  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.error) {
      setCaptions("Sesión no encontrada. Elegí otra.", { placeholder: true });
      return;
    }
    setCaptions(data.text, { interim: !data.is_final });
  };

  ws.onclose = () => {
    setStatus("desconectado", false);
  };
}

langButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    langButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentLang = btn.dataset.lang;
    connect();
  });
});

sessionSelect.addEventListener("change", connect);

refreshSessions();
setInterval(refreshSessions, 3000);
