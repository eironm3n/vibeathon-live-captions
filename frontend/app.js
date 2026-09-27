const sessionSelect = document.getElementById("session");
const langToggle = document.getElementById("lang-toggle");
const captionsEl = document.getElementById("captions");
const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("status-text");
const overlayLink = document.getElementById("overlay-link");
const srtLink = document.getElementById("srt-link");
const vttLink = document.getElementById("vtt-link");

let ws = null;
let sessions = [];
// "original" o "target": se recuerda la elección aunque cambie la sesión
// (y con ella el idioma destino concreto).
let langChoice = "original";

function currentSession() {
  return sessions.find((s) => s.id === sessionSelect.value) || null;
}

function currentLang() {
  const session = currentSession();
  return langChoice === "target" && session ? session.target_lang : "original";
}

function updateLinks() {
  const session = currentSession();
  const links = [overlayLink, srtLink, vttLink];
  if (!session) {
    links.forEach((a) => a.classList.add("disabled"));
    return;
  }
  links.forEach((a) => a.classList.remove("disabled"));
  const id = encodeURIComponent(session.id);
  const lang = encodeURIComponent(currentLang());
  overlayLink.href = `overlay.html?session=${id}&lang=${lang}`;
  srtLink.href = `/api/sessions/${id}/export?lang=${lang}&fmt=srt`;
  vttLink.href = `/api/sessions/${id}/export?lang=${lang}&fmt=vtt`;
}

function renderLangToggle() {
  const session = currentSession();
  langToggle.replaceChildren();
  const options = [["original", "Idioma original"]];
  if (session) options.push(["target", languageLabel(session.target_lang)]);
  options.forEach(([choice, label]) => {
    const btn = document.createElement("button");
    btn.className = "lang-btn";
    btn.dataset.lang = choice === "original" ? "original" : session.target_lang;
    btn.textContent = label;
    btn.classList.toggle("active", choice === langChoice);
    btn.addEventListener("click", () => {
      langChoice = choice;
      renderLangToggle();
      connect();
    });
    langToggle.appendChild(btn);
  });
}

function setStatus(text, live) {
  statusTextEl.textContent = text;
  statusEl.classList.toggle("live", Boolean(live));
}

function setCaptions(text, { placeholder = false } = {}) {
  captionsEl.textContent = text;
  captionsEl.classList.toggle("placeholder", placeholder);
  // Reinicia la animación de entrada en cada actualización.
  captionsEl.style.animation = "none";
  void captionsEl.offsetWidth;
  captionsEl.style.animation = "";
}

function disconnect() {
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
}

async function refreshSessions() {
  let data;
  try {
    const res = await fetch("/api/sessions");
    data = await res.json();
  } catch {
    setStatus("sin conexión con el servidor", false);
    return;
  }
  sessions = data.sessions;
  const previous = sessionSelect.value;

  sessionSelect.replaceChildren();
  if (sessions.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "Sin sesiones activas";
    opt.disabled = true;
    opt.selected = true;
    sessionSelect.appendChild(opt);
    disconnect();
    setStatus("desconectado", false);
    setCaptions("No hay sesiones en vivo en este momento.", { placeholder: true });
    renderLangToggle();
    updateLinks();
    return;
  }

  sessions.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.id;
    sessionSelect.appendChild(opt);
  });

  if (sessions.some((s) => s.id === previous)) {
    sessionSelect.value = previous;
    if (!ws) connect();
  } else {
    renderLangToggle();
    connect();
  }
}

function connect() {
  const session = currentSession();
  if (!session) return;

  disconnect();
  updateLinks();

  const lang = currentLang();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws/captions/${encodeURIComponent(session.id)}?lang=${encodeURIComponent(lang)}`;
  ws = new WebSocket(url);

  setStatus("conectando...", false);
  setCaptions("Esperando audio...", { placeholder: true });

  ws.onopen = () => {
    setStatus(`en vivo · ${session.id} · ${lang === "original" ? "original" : languageLabel(lang)}`, true);
  };

  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.type === "caption") {
      setCaptions(data.text);
    } else if (data.type === "ended") {
      setCaptions("La sesión terminó.", { placeholder: true });
    } else if (data.type === "error") {
      setCaptions("Sesión no encontrada. Elegí otra.", { placeholder: true });
    }
  };

  ws.onclose = () => {
    ws = null;
    setStatus("desconectado", false);
  };
}

sessionSelect.addEventListener("change", () => {
  renderLangToggle();
  connect();
});

renderLangToggle();
refreshSessions();
setInterval(refreshSessions, 3000);
