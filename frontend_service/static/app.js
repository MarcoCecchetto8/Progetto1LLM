// Pagina di chat di Pico: parla solo con il back-end (indirizzo da /config.js).
"use strict";

const BACKEND = ((window.APP_CONFIG && window.APP_CONFIG.backendUrl) || "http://127.0.0.1:8002").replace(/\/+$/, "");
const LAST_CHAT_KEY = "pico.ultimaChat";
const REVIEW_RETRY = "[revisore] non coerente";
// Errori arrivati come evento SSE: si trattano come le risposte HTTP con lo stesso codice.
const STREAM_ERROR_STATUS = {
  chat_non_trovata: 404, turno_in_corso: 409, conferma_in_attesa: 409, nessuna_conferma: 409,
};

const $ = (id) => document.getElementById(id);
const el = {
  body: document.body,
  rail: $("rail"), scrim: $("scrim"), menu: $("menu"),
  newChat: $("new-chat"), chatList: $("chat-list"), chatListEmpty: $("chat-list-empty"),
  title: $("chat-title"), turnState: $("turn-state"),
  thread: $("thread"), welcome: $("welcome"), messages: $("messages"),
  alert: $("alert"), alertText: $("alert-text"), alertRetry: $("alert-retry"), alertClose: $("alert-close"),
  confirm: $("confirm"), confirmList: $("confirm-list"), confirmSend: $("confirm-send"),
  composer: $("composer"), question: $("question"), send: $("send"), stop: $("stop"),
};

const state = {
  chats: [],
  chatId: null,
  busy: false,
  controller: null,
  retry: null,
  pendingView: null, // turno sospeso in attesa di conferma: domanda e schede ancora a schermo
  turnStarted: null, // istante d'inizio del turno in corso, per il contatore dei secondi
  ticker: null,
};

// ── Errori e chiamate al back-end ──

class UiError extends Error {
  constructor(message, status = null, code = null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function backendDown() {
  return new UiError(`Il back-end non risponde all'indirizzo ${BACKEND}: controlla che sia avviato (python -m backend_service).`);
}

async function errorFromResponse(response) {
  let data = null;
  try { data = await response.json(); } catch (_) { /* corpo non JSON */ }
  if (data && typeof data.messaggio === "string" && data.messaggio) {
    return new UiError(data.messaggio, response.status, data.codice || null);
  }
  if (response.status === 422) return new UiError("Richiesta non valida.", 422);
  return new UiError(`Risposta inattesa dal back-end (codice ${response.status}).`, response.status);
}

async function request(method, path, body, signal) {
  const options = { method, signal };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(BACKEND + path, options);
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    throw backendDown();
  }
  if (!response.ok) throw await errorFromResponse(response);
  return response;
}

async function api(method, path, body) {
  const response = await request(method, path, body);
  if (response.status === 204) return null;
  try { return await response.json(); } catch (_) { throw new UiError(`Risposta inattesa dal back-end (codice ${response.status}).`); }
}

// Legge un flusso SSE: blocchi separati da riga vuota, righe ":" di keepalive ignorate.
async function readSse(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const flush = (block) => {
    let name = "message";
    const data = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon < 0 ? line : line.slice(0, colon);
      const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "event") name = value;
      else if (field === "data") data.push(value);
    }
    if (!data.length) return;
    let payload;
    try { payload = JSON.parse(data.join("\n")); } catch (_) { return; }
    onEvent(name, payload);
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    // un «\r» in fondo al pezzo può essere metà di un «\r\n»: si normalizza al pezzo dopo
    buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n").replace(/\r(?=[\s\S])/g, "\n");
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      flush(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) flush(buffer.replace(/\r\n?/g, "\n"));
}

// ── Testo del modello: escape totale, poi solo **grassetto**, `codice`, blocchi ``` e a capo ──

function inlineNodes(text, parent) {
  const parts = text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/);
  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      parent.append(strong);
    } else if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      const code = document.createElement("code");
      code.textContent = part.slice(1, -1);
      parent.append(code);
    } else {
      const lines = part.split("\n");
      lines.forEach((line, index) => {
        if (index) parent.append(document.createElement("br"));
        if (line) parent.append(document.createTextNode(line));
      });
    }
  }
}

function renderText(text) {
  const fragment = document.createDocumentFragment();
  const chunks = String(text || "").split("```");
  chunks.forEach((chunk, index) => {
    if (index % 2 === 1) {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = chunk.replace(/^[^\n]*\n/, "").replace(/\n$/, "");
      pre.append(code);
      fragment.append(pre);
      return;
    }
    for (const paragraph of chunk.split(/\n{2,}/)) {
      const trimmed = paragraph.replace(/^\n+|\n+$/g, "");
      if (!trimmed) continue;
      const p = document.createElement("p");
      if (trimmed.startsWith("⚠")) p.className = "warn";
      inlineNodes(trimmed, p);
      fragment.append(p);
    }
  });
  return fragment;
}

// ── Formati ──

const decimal = new Intl.NumberFormat("it-IT", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const timeFormat = new Intl.DateTimeFormat("it-IT", { hour: "2-digit", minute: "2-digit" });
const dayFormat = new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "short" });

function chatDate(chat) {
  const value = chat.ultimo_messaggio || chat.creata;
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const sameDay = (a, b) => a.toDateString() === b.toDateString();
  if (sameDay(date, today)) return `oggi ${timeFormat.format(date)}`;
  if (sameDay(date, yesterday)) return `ieri ${timeFormat.format(date)}`;
  return dayFormat.format(date);
}

function formatArgs(args) {
  const entries = Object.entries(args || {});
  if (!entries.length) return "nessun dato";
  return entries.map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`).join(" · ");
}

const seconds = (ms) => `${decimal.format(ms / 1000)} s`;

// ── Elementi della conversazione ──

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function toolCard(tool, number) {
  const card = make("div", "tool");
  card.dataset.state = tool.esito == null ? "running" : (tool.errore ? "error" : "ok");
  const num = make("div", "tool-num");
  num.append("Scheda", make("b", "", String(number)));
  const body = make("div", "tool-body");
  body.append(
    make("span", "tool-name", tool.nome),
    make("span", "tool-args", formatArgs(tool.argomenti)),
    make("span", "tool-result", tool.esito == null ? "in esecuzione" : resultText(tool.esito, tool.errore)),
  );
  card.append(num, body);
  return card;
}

function resultText(content, error) {
  return error ? `errore: ${content}` : content;
}

function finishToolCard(card, content, error) {
  card.dataset.state = error ? "error" : "ok";
  card.querySelector(".tool-result").textContent = resultText(content, error);
}

// Righe informative del turno («[revisore] coerente») mostrate come cartellino: «Revisore · coerente».
function infoLine(text) {
  const raw = String(text || "");
  const match = raw.match(/^\[([^\]]+)\]\s*(.*)$/s);
  const line = make("p", "review-note");
  if (!match) {
    line.textContent = raw;
    return line;
  }
  const label = match[1].charAt(0).toUpperCase() + match[1].slice(1);
  line.append(make("span", "review-label", label), make("span", "", match[2]));
  if (/^non coerente/i.test(match[2])) line.classList.add("review-bad");
  return line;
}

function toolCount() {
  return el.messages.querySelectorAll(".tool").length;
}

function userMessage(text) {
  const item = make("li", "msg-user");
  item.textContent = text;
  return item;
}

function assistantMessage(message) {
  const item = make("li", "msg-assistant");
  let number = toolCount();
  for (const tool of message.strumenti || []) {
    number += 1;
    item.append(toolCard(tool, number));
  }
  const answer = make("div", "answer");
  answer.append(renderText(message.contenuto));
  item.append(answer);
  for (const line of message.righe || []) item.append(infoLine(line));
  return item;
}

function metricsLine(metrics) {
  const line = make("p", "note-line metrics");
  line.append(make("b", "", seconds(metrics.total)), " in tutto");
  if (metrics.firstToken != null) line.append(" · primo token dopo ", make("b", "", seconds(metrics.firstToken)));
  line.append(" · ", make("b", "", `≈ ${metrics.tokens}`), " token");
  line.title = "Misurate nel browser dall'invio; i token sono i pezzi di risposta arrivati in streaming.";
  return line;
}

function scrollToEnd() {
  el.thread.scrollTop = el.thread.scrollHeight;
}

// ── Stato della pagina ──

const STATE_TEXT = {
  idle: "", waiting: "in attesa", tool: "strumento in corso", writing: "risponde",
  review: "in revisione", done: "completato", stopped: "interrotto", confirm: "conferma richiesta", error: "errore",
};

function setTurnState(name) {
  el.turnState.dataset.state = name;
  el.turnState.textContent = STATE_TEXT[name] || "";
  if (state.turnStarted != null && el.turnState.textContent) {
    // secondi trascorsi: aria-hidden, così il lettore di schermo non li annuncia a ogni scatto
    const timer = make("span", "turn-timer");
    timer.setAttribute("aria-hidden", "true");
    el.turnState.append(timer);
    tickTimer();
  }
}

function tickTimer() {
  const timer = el.turnState.querySelector(".turn-timer");
  if (timer && state.turnStarted != null) {
    timer.textContent = ` · ${Math.floor((performance.now() - state.turnStarted) / 1000)} s`;
  }
}

function setBusy(busy) {
  if (busy && state.ticker == null) {
    state.turnStarted = performance.now();
    state.ticker = setInterval(tickTimer, 1000);
  } else if (!busy && state.ticker != null) {
    clearInterval(state.ticker);
    state.ticker = null;
    state.turnStarted = null;
  }
  state.busy = busy;
  el.send.hidden = busy;
  el.stop.hidden = !busy;
  el.question.readOnly = busy;
  el.newChat.disabled = busy;
  el.thread.setAttribute("aria-busy", String(busy));
  updateSend();
}

function updateSend() {
  el.send.disabled = state.busy || !el.question.value.trim();
}

function showAlert(message, { retry = null, tone = "error" } = {}) {
  el.alertText.textContent = message;
  el.alert.dataset.tone = tone;
  state.retry = retry;
  el.alertRetry.hidden = !retry;
  el.alert.hidden = false;
}

function hideAlert() {
  el.alert.hidden = true;
  state.retry = null;
}

function rememberChat(id) {
  try {
    if (id == null) localStorage.removeItem(LAST_CHAT_KEY);
    else localStorage.setItem(LAST_CHAT_KEY, String(id));
  } catch (_) { /* archivio del browser non disponibile */ }
}

function rememberedChat() {
  try { return Number(localStorage.getItem(LAST_CHAT_KEY)) || null; } catch (_) { return null; }
}

function closeMenu() {
  el.body.classList.remove("menu-open");
  el.scrim.hidden = true;
  el.menu.setAttribute("aria-expanded", "false");
}

// ── Elenco delle chat ──

function renderChatList() {
  el.chatList.replaceChildren();
  el.chatListEmpty.hidden = state.chats.length > 0;
  for (const chat of state.chats) {
    const item = make("li", "chat-item");
    if (chat.id === state.chatId) item.setAttribute("aria-current", "true");
    const open = make("button", "chat-open");
    open.type = "button";
    const meta = make("span", "chat-date");
    meta.append(make("span", "chat-num", `n. ${chat.id}`), ` · ${chatDate(chat)}`);
    open.append(make("span", "chat-title", chat.titolo), meta);
    open.addEventListener("click", () => openChat(chat.id));
    const remove = make("button", "chat-delete");
    remove.type = "button";
    remove.setAttribute("aria-label", `Elimina la chat «${chat.titolo}»`);
    remove.title = "Elimina la chat";
    remove.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4h11M6.5 4V2.5h3V4M4 4l.7 9.5h6.6L12 4M6.8 6.5v4.5M9.2 6.5v4.5"/></svg>';
    remove.addEventListener("click", () => deleteChat(chat));
    item.append(open, remove);
    el.chatList.append(item);
  }
}

async function loadChats() {
  try {
    state.chats = await api("GET", "/chats");
    renderChatList();
    return true;
  } catch (error) {
    showAlert(error.message, { retry: () => start() });
    return false;
  }
}

// ── Apertura, vista vuota, eliminazione ──

function showEmpty() {
  state.chatId = null;
  rememberChat(null);
  el.title.textContent = "Nuova chat";
  el.messages.replaceChildren();
  el.welcome.hidden = false;
  hideConfirm();
  setTurnState("idle");
  renderChatList();
}

function renderChat(detail) {
  el.title.textContent = detail.titolo;
  el.messages.replaceChildren();
  for (const message of detail.messaggi) {
    el.messages.append(message.ruolo === "utente" ? userMessage(message.contenuto) : assistantMessage(message));
  }
  el.welcome.hidden = detail.messaggi.length > 0 || detail.conferme.length > 0;
  if (detail.conferme.length) {
    showConfirm(detail.conferme);
    setTurnState("confirm");
  } else {
    hideConfirm();
  }
}

async function openChat(id, { quiet = false } = {}) {
  if (state.busy && !quiet) {
    showAlert("Attendi la fine della risposta, oppure interrompila.", { tone: "info" });
    return null;
  }
  try {
    const detail = await api("GET", `/chats/${id}`);
    state.chatId = detail.id;
    rememberChat(detail.id);
    if (!quiet) { hideAlert(); setTurnState("idle"); }
    renderChat(detail);
    renderChatList();
    closeMenu();
    scrollToEnd();
    return detail;
  } catch (error) {
    if (error.status === 404) {
      showEmpty();
      await loadChats();
    }
    showAlert(error.message, error.status === 404 ? {} : { retry: () => openChat(id) });
    return null;
  }
}

async function deleteChat(chat) {
  if (state.busy) {
    showAlert("Attendi la fine della risposta, oppure interrompila.", { tone: "info" });
    return;
  }
  if (!window.confirm(`Eliminare la chat «${chat.titolo}»? I messaggi non si possono recuperare.`)) return;
  try {
    await api("DELETE", `/chats/${chat.id}`);
  } catch (error) {
    if (error.status !== 404) { showAlert(error.message); return; }
  }
  if (chat.id === state.chatId) showEmpty();
  await loadChats();
}

// ── Conferma delle eliminazioni ──

function showConfirm(confirmations) {
  el.confirmList.replaceChildren();
  for (const item of confirmations) {
    const box = make("fieldset", "confirm-item");
    box.dataset.note = String(item.id_nota);
    box.append(make("legend", "", item.domanda.replace(/\s*\[s\/N\]\s*$/i, "")));
    const choices = make("div", "choices");
    for (const [value, label, extra] of [["true", "Elimina", "danger"], ["false", "Non eliminare", ""]]) {
      const choice = make("label", `choice ${extra}`.trim());
      const input = document.createElement("input");
      input.type = "radio";
      input.name = `nota-${item.id_nota}`;
      input.value = value;
      input.checked = value === "false";
      choice.append(input, make("span", "", label));
      choices.append(choice);
    }
    box.append(choices);
    el.confirmList.append(box);
  }
  el.confirm.hidden = false;
  el.composer.hidden = true;
  el.confirmSend.disabled = false;
}

function hideConfirm() {
  el.confirm.hidden = true;
  el.composer.hidden = false;
}

function confirmDecisions() {
  const decisions = {};
  for (const box of el.confirmList.querySelectorAll(".confirm-item")) {
    const checked = box.querySelector("input:checked");
    decisions[box.dataset.note] = checked ? checked.value === "true" : false;
  }
  return decisions;
}

// ── Un turno in streaming ──

function turnView(text) {
  const view = { user: null, item: make("li", "msg-assistant"), answer: null, cards: [], draft: "" };
  if (text) {
    view.user = userMessage(text);
    el.messages.append(view.user);
  }
  view.answer = make("div", "answer answer-pending");
  view.answer.append(make("p", "", "Pico sta pensando"));
  view.answer.firstChild.append(make("span", "dots"));
  view.item.append(view.answer);
  el.messages.append(view.item);
  el.welcome.hidden = true;
  scrollToEnd();
  return view;
}

function removeView(view) {
  if (view.user) view.user.remove();
  view.item.remove();
}

async function runTurn(path, body, view, text) {
  const chatId = state.chatId;
  const controller = new AbortController();
  state.controller = controller;
  setBusy(true);
  setTurnState("waiting");
  const started = performance.now();
  const metrics = { firstToken: null, tokens: 0, total: 0 };
  let outcome = null;
  try {
    const response = await request("POST", path, body, controller.signal);
    await readSse(response, (name, data) => {
      if (name === "strumento") {
        const card = toolCard({ nome: data.nome, argomenti: data.argomenti, esito: null }, toolCount() + 1);
        view.cards.push(card);
        view.item.insertBefore(card, view.answer);
        setTurnState("tool");
      } else if (name === "esito_strumento") {
        const card = view.cards.find((c) => c.dataset.state === "running");
        if (card) finishToolCard(card, data.contenuto, data.errore);
        setTurnState("waiting");
      } else if (name === "risposta") {
        if (metrics.firstToken == null) metrics.firstToken = performance.now() - started;
        metrics.tokens += 1;
        view.draft += data.testo || "";
        view.answer.classList.remove("answer-pending");
        view.answer.replaceChildren(renderText(view.draft));
        setTurnState("writing");
      } else if (name === "riga") {
        const line = String(data.testo || "");
        if (line.startsWith(REVIEW_RETRY)) {
          view.draft = "";
          view.answer.classList.add("answer-pending");
          view.answer.replaceChildren(make("p", "", "Il revisore ha chiesto di rivedere la risposta"));
          view.answer.firstChild.append(make("span", "dots"));
          setTurnState("review");
        }
        view.item.append(infoLine(line));
      } else if (name === "fine") {
        outcome = data;
      } else if (name === "errore") {
        throw new UiError(data.messaggio || "Errore durante la risposta.", STREAM_ERROR_STATUS[data.codice] || null, data.codice || null);
      }
      scrollToEnd();
    });
    if (!outcome) throw new UiError("La risposta si è interrotta prima della fine. Riprova.");
  } catch (error) {
    state.controller = null;
    setBusy(false);
    removeView(view);
    if (error && error.name === "AbortError") {
      setTurnState("stopped");
      await afterStop(chatId, text);
      return;
    }
    setTurnState("error");
    if (text && !el.question.value) el.question.value = text;
    updateSend();
    if (error.status === 404) { showEmpty(); await loadChats(); }
    else if (error.status === 409 || !text) {
      // conferma fallita o chat occupata: si riallinea a ciò che il back-end ha salvato
      if (state.pendingView) { removeView(state.pendingView); state.pendingView = null; }
      await openChat(chatId, { quiet: true });
      setTurnState("error");
    }
    showAlert(error.message || String(error));
    return;
  }
  state.controller = null;
  setBusy(false);
  metrics.total = performance.now() - started;
  if (outcome.esito === "conferma_richiesta") {
    view.answer.remove();
    for (const card of view.cards) {
      if (card.dataset.state === "running") card.querySelector(".tool-result").textContent = "in attesa di conferma";
    }
    showConfirm(outcome.conferme || []);
    setTurnState("confirm");
    state.pendingView = view;
    scrollToEnd();
    return;
  }
  // la vista provvisoria resta finché la chat salvata non è arrivata
  const provisional = [view, state.pendingView].filter(Boolean);
  state.pendingView = null;
  const detail = await openChat(chatId, { quiet: true });
  if (!detail) for (const item of provisional) item.item.classList.add("is-stale");
  if (detail) {
    const last = el.messages.querySelector(".msg-assistant:last-child");
    if (last && metrics.tokens) last.append(metricsLine(metrics));
    setTurnState("done");
  }
  await loadChats();
  scrollToEnd();
}

// Dopo «Interrompi» il back-end può aver salvato comunque: si rilegge la chat.
async function afterStop(chatId, text) {
  if (state.pendingView) { removeView(state.pendingView); state.pendingView = null; }
  let saved = false;
  if (chatId != null) {
    const detail = await openChat(chatId, { quiet: true });
    if (detail && text) {
      const users = detail.messaggi.filter((m) => m.ruolo === "utente");
      saved = users.length > 0 && users[users.length - 1].contenuto === text.trim();
    }
    await loadChats();
  }
  setTurnState("stopped");
  if (text && !saved && !el.question.value) el.question.value = text;
  updateSend();
  showAlert(saved
    ? "Risposta interrotta, ma Pico aveva già finito: la risposta è salvata."
    : "Risposta interrotta. Se Pico era quasi alla fine, la risposta potrebbe comparire tra poco: riapri la chat per controllare.",
  { tone: "info", retry: chatId != null ? () => openChat(chatId) : null });
}

async function sendQuestion(raw) {
  const text = raw.trim();
  if (!text || state.busy) return;
  hideAlert();
  // occupato subito: un secondo Invio durante la creazione della chat non crea una chat doppia
  setBusy(true);
  el.question.value = "";
  if (state.chatId == null) {
    try {
      const chat = await api("POST", "/chats");
      state.chatId = chat.id;
      rememberChat(chat.id);
      el.title.textContent = chat.titolo;
      loadChats();
    } catch (error) {
      setBusy(false);
      el.question.value = text;
      updateSend();
      showAlert(error.message);
      return;
    }
  }
  const view = turnView(text);
  await runTurn(`/chats/${state.chatId}/messaggi/stream`, { testo: text }, view, text);
}

async function sendConfirm() {
  if (state.busy || state.chatId == null) return;
  hideAlert();
  const decisions = confirmDecisions();
  hideConfirm();
  const view = turnView(null);
  // le schede sospese (es. delete_note) ricevono l'esito nel flusso della ripresa
  if (state.pendingView) view.cards = state.pendingView.cards.filter((card) => card.dataset.state === "running");
  await runTurn(`/chats/${state.chatId}/conferma/stream`, { decisioni: decisions }, view, null);
}

// ── Eventi ──

el.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  sendQuestion(el.question.value);
});
el.question.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendQuestion(el.question.value);
  }
});
el.question.addEventListener("input", updateSend);
el.stop.addEventListener("click", () => { if (state.controller) state.controller.abort(); });
el.confirm.addEventListener("submit", (event) => { event.preventDefault(); sendConfirm(); });
el.newChat.addEventListener("click", () => { hideAlert(); showEmpty(); closeMenu(); el.question.focus(); });
el.alertClose.addEventListener("click", hideAlert);
el.alertRetry.addEventListener("click", () => { const retry = state.retry; hideAlert(); if (retry) retry(); });
for (const example of document.querySelectorAll(".example")) {
  example.addEventListener("click", () => sendQuestion(example.dataset.question));
}
el.menu.addEventListener("click", () => {
  const open = !el.body.classList.contains("menu-open");
  el.body.classList.toggle("menu-open", open);
  el.scrim.hidden = !open;
  el.menu.setAttribute("aria-expanded", String(open));
});
el.scrim.addEventListener("click", closeMenu);

async function start() {
  hideAlert();
  if (!(await loadChats())) return;
  const last = rememberedChat();
  if (last && state.chats.some((chat) => chat.id === last)) await openChat(last);
  else showEmpty();
}

start();
