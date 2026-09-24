"use strict";

/*
 * Own console (feature: own-console): vanilla JS + fetch against the
 * same-origin /api/v1 surface. No frameworks, no build step, no CDN — the
 * whole app runs offline from the three static files served by FastAPI.
 * UI copy is Spanish (product language); code comments are English.
 *
 * Endpoint paths are written in full (never assembled) so the integration
 * test can grep them on the served file.
 */

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function $(selector) {
  return document.querySelector(selector);
}

// Per-tab busy flag: disable every button inside the tab panel while a
// request is in flight, re-enable them when it settles.
const busy = { chat: false, learn: false, explore: false, memories: false, vault: false, map: false };

function setBusy(tab, on) {
  busy[tab] = on;
  const panel = document.getElementById(`panel-tab-${tab}`);
  if (!panel) return;
  panel.querySelectorAll("button, input[type='submit']").forEach((el) => {
    el.disabled = on;
  });
}

// --- error banner ----------------------------------------------------------

function hideError() {
  document.getElementById("error-banner").classList.add("hidden");
}

function showError(message) {
  document.getElementById("error-banner-text").textContent = message;
  document.getElementById("error-banner").classList.remove("hidden");
}

// FastAPI errors carry {"detail": ...}; surface that string when present.
// A non-JSON body (or a network failure) falls back to the raw message.
async function errorMessage(response, fallback) {
  try {
    const body = await response.json();
    if (body && body.detail !== undefined) {
      return typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail);
    }
  } catch {
    // Not a JSON error body; use the fallback.
  }
  return fallback;
}

// fetch wrapper: JSON in, JSON out; throws with the API detail on failure.
// A 204 (delete endpoints) resolves to null.
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(await errorMessage(response, `HTTP ${response.status}`));
  }
  if (response.status === 204) return null;
  return response.json();
}

function actionButton(label, kind, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = kind || "";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

// ---------------------------------------------------------------------------
// Minimal, safe markdown rendering (zero dependency; offline requirement).
//
// The input is HTML-escaped FIRST, so every transform below operates on
// escaped text and can never inject markup. Supported constructs: fenced
// code, h1-h3 headings, unordered/ordered lists, horizontal rules, bold and
// inline code. Anything we cannot handle safely renders preformatted.
// ---------------------------------------------------------------------------

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function inlineMd(line) {
  return line
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function renderMd(text) {
  const lines = escapeHtml(String(text == null ? "" : text)).split("\n");
  const out = [];
  let openList = null; // "ul" | "ol" when a list is open
  let fence = null; // accumulating code lines when not null

  const closeList = () => {
    if (openList) {
      out.push(`</${openList}>`);
      openList = null;
    }
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();

    // Fenced code blocks (opening line "```[lang]"): emit verbatim <pre>.
    if (trimmed.startsWith("```")) {
      if (fence !== null) {
        out.push(`<pre>${fence.join("\n")}</pre>`);
        fence = null;
      } else {
        fence = [];
      }
      continue;
    }
    if (fence !== null) {
      fence.push(line);
      continue;
    }

    // Headings: "# " .. "### " map to h1..h3 (already-escaped text).
    const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed);
    if (heading) {
      closeList();
      const level = heading[1].length;
      out.push(`<h${level}>${inlineMd(heading[2])}</h${level}>`);
      continue;
    }

    // Horizontal rules.
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      closeList();
      out.push("<hr>");
      continue;
    }

    // List items: "- item" and "1. item" (consecutive same-kind items group).
    const ordered = /^\d+\.\s+(.+)$/.exec(trimmed);
    const bullet = /^[-*]\s+(.+)$/.exec(trimmed);
    if (ordered || bullet) {
      const tag = ordered ? "ol" : "ul";
      if (openList !== tag) {
        closeList();
        out.push(`<${tag}>`);
        openList = tag;
      }
      const content = (ordered || bullet)[1];
      out.push(`<li>${inlineMd(content)}</li>`);
      continue;
    }

    // Blank line closes any open list.
    if (trimmed === "") {
      closeList();
      continue;
    }

    // Constructs we do not render (blockquotes, tables, images, >=4-hash
    // headings, indented code) fall back to a preformatted block. The text
    // is already escaped, so a leading "&gt;" is a blockquote line.
    if (
      trimmed.startsWith("&gt;") ||
      trimmed.startsWith("|") ||
      trimmed.startsWith("![") ||
      (trimmed.startsWith("#") && !/^#{1,3}\s/.test(trimmed)) ||
      /^ {4,}/.test(line)
    ) {
      closeList();
      out.push(`<pre>${line}</pre>`);
      continue;
    }

    // Plain paragraph line.
    closeList();
    out.push(`<p>${inlineMd(line)}</p>`);
  }

  if (fence !== null) {
    // Unclosed fence: emit what we have rather than dropping it.
    out.push(`<pre>${fence.join("\n")}</pre>`);
  }
  closeList();
  return out.join("\n");
}

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------

const loaded = { memories: false, vault: false, explore: false };

function activateTab(id) {
  document.querySelectorAll(".tab").forEach((button) => {
    const active = button.dataset.tab === id;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.panel !== id);
  });
  hideError();
  if (id === "explore" && !loaded.explore) {
    loaded.explore = true;
    loadSessions();
  }
  if (id === "memories" && !loaded.memories) {
    loaded.memories = true;
    loadMemories();
  }
  if (id === "vault" && !loaded.vault) {
    loaded.vault = true;
    loadDocuments();
  }
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});

// ---------------------------------------------------------------------------
// Tab 1: Chat -> POST /api/v1/chat {message, top_k}
// ---------------------------------------------------------------------------

document.getElementById("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = document.getElementById("chat-message").value.trim();
  if (!message) return;
  const topK = Math.max(1, Number.parseInt(document.getElementById("chat-top-k").value, 10) || 5);

  setBusy("chat", true);
  hideError();
  try {
    const data = await api("/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, top_k: topK }),
    });
    document.getElementById("chat-answer").innerHTML = renderMd(data.answer || "");
    renderSources("chat-sources", data.sources);
    document.getElementById("chat-output").classList.remove("hidden");
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("chat", false);
  }
});

// Shared renderer for {title, score} source lists (chat and learn responses).
function renderSources(listId, sources) {
  const list = document.getElementById(listId);
  list.innerHTML = "";
  const items = Array.isArray(sources) ? sources : [];
  if (items.length === 0) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "Sin fuentes.";
    list.appendChild(empty);
    return;
  }
  for (const source of items) {
    const li = document.createElement("li");
    const title = document.createElement("span");
    title.textContent = source.title || "(sin título)";
    const score = document.createElement("span");
    score.className = "source-score";
    score.textContent = `relevancia ${Number(source.score ?? 0).toFixed(2)}`;
    li.append(title, score);
    list.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// Tab 2: Aprender -> POST /api/v1/learn/run {goal, mode, allow_research}
// ---------------------------------------------------------------------------

document.getElementById("learn-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const goal = document.getElementById("learn-goal").value.trim();
  if (!goal) return;
  const mode = document.getElementById("learn-mode").value;
  const allowResearch = document.getElementById("learn-allow-research").checked;

  setBusy("learn", true);
  hideError();
  try {
    const data = await api("/api/v1/learn/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal, mode, allow_research: allowResearch }),
    });
    const tutorial = data.tutorial || {};
    document.getElementById("learn-needs-research").textContent = data.needs_research
      ? "Se detectó un vacío de conocimiento (research activo en los resultados)."
      : "El vault tenía conocimiento suficiente.";
    document.getElementById("learn-file-path").textContent = tutorial.file_path || "—";
    const researchPath = data.research && data.research.file_path ? data.research.file_path : "—";
    document.getElementById("learn-research-path").textContent = researchPath;
    document.getElementById("learn-tutorial").innerHTML = renderMd(tutorial.content || "");
    renderSources("learn-sources", tutorial.sources);
    document.getElementById("learn-reflect-hint").textContent = data.reflect_hint || "";
    document.getElementById("learn-output").classList.remove("hidden");
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("learn", false);
  }
});

// ---------------------------------------------------------------------------
// Tab 3: Explorar -> POST/GET /api/v1/research/sessions (research sessions)
// ---------------------------------------------------------------------------

// The session currently open in the thread view ({id, title, ...} or null).
let currentSession = null;

async function loadSessions() {
  const select = document.getElementById("explore-session");
  setBusy("explore", true);
  hideError();
  try {
    const data = await api("/api/v1/research/sessions");
    const items = Array.isArray(data.items) ? data.items : [];
    select.innerHTML = "";
    if (items.length === 0) {
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "No hay sesiones todavía. Creá una nueva.";
      select.appendChild(empty);
    } else {
      for (const session of items) {
        const option = document.createElement("option");
        option.value = session.id;
        option.textContent = `${session.title} (${session.turn_count} turnos)`;
        select.appendChild(option);
      }
    }
    if (currentSession && items.some((s) => s.id === currentSession.id)) {
      select.value = currentSession.id;
    }
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("explore", false);
  }
}

async function openSession(id) {
  setBusy("explore", true);
  hideError();
  try {
    const session = await api(`/api/v1/research/sessions/${id}`);
    currentSession = session;
    renderThread(session.turns || []);
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("explore", false);
  }
}

function renderThread(turns) {
  const container = document.getElementById("explore-thread");
  container.innerHTML = "";
  if (turns.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent =
      "Todavía no hay mensajes. Escribí una pregunta o pedí una búsqueda web.";
    container.appendChild(empty);
    return;
  }
  for (const turn of turns) {
    container.appendChild(renderTurn(turn));
  }
  container.scrollTop = container.scrollHeight;
}

function renderTurn(turn) {
  const div = document.createElement("div");
  div.className = `turn turn-${turn.role}`;

  const role = document.createElement("div");
  role.className = "turn-role muted";
  role.textContent =
    turn.role === "user"
      ? "Vos"
      : turn.kind === "research"
        ? "Investigación web"
        : "Asistente";

  const content = document.createElement("div");
  content.className = "content";
  content.innerHTML = renderMd(turn.content || "");
  div.append(role, content);

  if (Array.isArray(turn.sources) && turn.sources.length > 0) {
    const ul = document.createElement("ul");
    ul.className = "sources";
    for (const source of turn.sources) {
      const li = document.createElement("li");
      const title = document.createElement("span");
      title.textContent = source.title || "(sin título)";
      li.appendChild(title);
      if (source.url) {
        const link = document.createElement("a");
        link.href = source.url;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = source.url;
        li.appendChild(document.createTextNode(" — "));
        li.appendChild(link);
      }
      ul.appendChild(li);
    }
    div.appendChild(ul);
  }
  return div;
}

async function sendExploreMessage(message) {
  if (!currentSession) return;
  setBusy("explore", true);
  hideError();
  try {
    await api(`/api/v1/research/sessions/${currentSession.id}/turn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    // Reload the thread: the server persisted both the user turn and the
    // assistant answer (research reports live server-side too).
    await openSession(currentSession.id);
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("explore", false);
  }
}

document.getElementById("explore-new").addEventListener("click", async () => {
  setBusy("explore", true);
  hideError();
  try {
    const session = await api("/api/v1/research/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    currentSession = session;
    await loadSessions();
    await openSession(session.id);
    document.getElementById("explore-message").focus();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("explore", false);
  }
});

document.getElementById("explore-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = document.getElementById("explore-message").value.trim();
  if (!message || !currentSession) return;
  document.getElementById("explore-message").value = "";
  await sendExploreMessage(message);
});

document.getElementById("explore-session").addEventListener("change", (event) => {
  if (event.target.value) {
    openSession(event.target.value);
  }
});

document.getElementById("explore-tutorial").addEventListener("click", async () => {
  if (!currentSession) return;
  const mode = document.getElementById("explore-mode").value;
  setBusy("explore", true);
  hideError();
  try {
    const result = await api(`/api/v1/research/sessions/${currentSession.id}/tutorial`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    document.getElementById("explore-tutorial-path").textContent =
      result.file_path || "—";
    document.getElementById("explore-tutorial-result").classList.remove("hidden");
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("explore", false);
  }
});

// ---------------------------------------------------------------------------
// Tab 4: Memorias -> list, approve/reject/delete, extract
// ---------------------------------------------------------------------------

async function loadMemories() {
  const params = new URLSearchParams();
  const type = document.getElementById("memory-type").value;
  const status = document.getElementById("memory-status").value;
  if (type) params.set("type", type);
  if (status) params.set("status", status);

  const container = document.getElementById("memories-list");
  setBusy("memories", true);
  hideError();
  try {
    const data = await api(`/api/v1/memories?${params.toString()}`);
    const items = Array.isArray(data.items) ? data.items : [];
    container.innerHTML = "";
    if (items.length === 0) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No hay memorias con esos filtros.";
      container.appendChild(empty);
      return;
    }
    for (const memory of items) {
      container.appendChild(renderMemoryRow(memory));
    }
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("memories", false);
  }
}

function renderMemoryRow(memory) {
  const row = document.createElement("div");
  row.className = "memory-row";

  const head = document.createElement("div");
  head.className = "memory-head";
  const status = document.createElement("span");
  status.className = `memory-${memory.status || "candidate"}`;
  status.textContent = memory.status || "candidate";
  const type = document.createElement("span");
  type.className = "memory-type";
  type.textContent = memory.memory_type || "";
  const confidence = document.createElement("span");
  confidence.className = "memory-confidence muted";
  confidence.textContent = `confianza ${Number(memory.confidence ?? 0).toFixed(2)}`;
  head.append(status, type, confidence);

  const content = document.createElement("p");
  content.className = "memory-content";
  content.textContent = memory.content || "";

  const actions = document.createElement("div");
  actions.className = "memory-actions";
  // approve/reject are only valid for candidates (the API answers 409 otherwise).
  if (memory.status === "candidate") {
    actions.appendChild(actionButton("Aprobar", "ok", () => setMemoryStatus(memory.id, "approve")));
    actions.appendChild(actionButton("Rechazar", "secondary", () => setMemoryStatus(memory.id, "reject")));
  }
  actions.appendChild(actionButton("Eliminar", "danger", () => deleteMemory(memory.id)));

  row.append(head, content, actions);
  return row;
}

async function setMemoryStatus(id, action) {
  setBusy("memories", true);
  hideError();
  try {
    await api(`/api/v1/memories/${id}/${action}`, { method: "POST" });
    await loadMemories();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("memories", false);
  }
}

async function deleteMemory(id) {
  if (!window.confirm("¿Eliminar esta memoria (fila, vector y espejo)?")) return;
  setBusy("memories", true);
  hideError();
  try {
    await api(`/api/v1/memories/${id}`, { method: "DELETE" });
    await loadMemories();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("memories", false);
  }
}

document.getElementById("memories-reload").addEventListener("click", loadMemories);
document.getElementById("memory-type").addEventListener("change", loadMemories);
document.getElementById("memory-status").addEventListener("change", loadMemories);

// Extract candidates from a conversation: one user line per textarea line.
document.getElementById("extract-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const turns = document
    .getElementById("extract-conversation")
    .value.split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (turns.length === 0) return;

  setBusy("memories", true);
  hideError();
  try {
    const data = await api("/api/v1/memories/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation: turns.map((content) => ({ role: "user", content })),
      }),
    });
    const candidates = Array.isArray(data.candidates) ? data.candidates : [];
    const list = document.getElementById("extract-candidates");
    list.innerHTML = "";
    if (candidates.length === 0) {
      const empty = document.createElement("li");
      empty.className = "muted";
      empty.textContent = "No se detectaron memorias candidatas.";
      list.appendChild(empty);
    } else {
      for (const candidate of candidates) {
        const li = document.createElement("li");
        li.textContent = `[${candidate.memory_type}] ${candidate.content} (confianza ${Number(
          candidate.confidence ?? 0
        ).toFixed(2)})`;
        list.appendChild(li);
      }
    }
    document.getElementById("extract-output").classList.remove("hidden");
    await loadMemories(); // the candidates are persisted; refresh the list
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("memories", false);
  }
});

// ---------------------------------------------------------------------------
// Tab 5: Vault -> list (with stale badge), upload, resync, append, delete
// ---------------------------------------------------------------------------

async function loadDocuments() {
  const container = document.getElementById("documents-list");
  const select = document.getElementById("append-document");
  setBusy("vault", true);
  hideError();
  try {
    const data = await api("/api/v1/documents");
    const items = Array.isArray(data.items) ? data.items : [];

    // The list payload has no `stale` flag; fetch the per-document detail so
    // the UI can show the badge (the two-session workflow needs it).
    const rows = await Promise.all(
      items.map(async (doc) => {
        let stale = false;
        try {
          const detail = await api(`/api/v1/documents/${doc.id}`);
          stale = Boolean(detail.stale);
        } catch {
          // Detail failed; render the row without a stale badge.
        }
        return { doc, stale };
      })
    );

    select.innerHTML = "";
    if (items.length === 0) {
      const emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = "No hay documentos aún";
      select.appendChild(emptyOption);
      const empty = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.className = "muted";
      cell.textContent = "El vault está vacío. Subí un documento para empezar.";
      empty.appendChild(cell);
      container.innerHTML = "";
      container.appendChild(empty);
      return;
    }

    container.innerHTML = "";
    for (const { doc, stale } of rows) {
      container.appendChild(renderDocumentRow(doc, stale));
      const option = document.createElement("option");
      option.value = doc.id;
      option.textContent = doc.title || "(sin título)";
      select.appendChild(option);
    }
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("vault", false);
  }
}

function renderDocumentRow(doc, stale) {
  const tr = document.createElement("tr");

  const title = document.createElement("td");
  title.textContent = doc.title || "(sin título)";
  title.title = doc.id;

  // The DocumentRead payload has no project_id; its mime type is shown instead.
  const type = document.createElement("td");
  type.className = "muted";
  type.textContent = doc.mime_type || "";

  const state = document.createElement("td");
  if (stale) {
    const badge = document.createElement("span");
    badge.className = "badge badge-stale";
    badge.textContent = "stale";
    state.appendChild(badge);
  } else {
    state.textContent = "—";
  }

  const actions = document.createElement("td");
  actions.className = "row-actions";
  actions.appendChild(actionButton("Anexar", "secondary", () => openAppend(doc)));
  actions.appendChild(actionButton("Resincronizar", "secondary", () => resyncDocument(doc.id)));
  actions.appendChild(actionButton("Eliminar", "danger", () => deleteDocument(doc.id)));

  tr.append(title, type, state, actions);
  return tr;
}

function openAppend(doc) {
  const select = document.getElementById("append-document");
  if ([...select.options].some((option) => option.value === doc.id)) {
    select.value = doc.id;
  }
  document.getElementById("append-text").focus();
}

document.getElementById("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const fileInput = document.getElementById("upload-file");
  const file = fileInput.files && fileInput.files[0];
  if (!file) return;

  setBusy("vault", true);
  hideError();
  try {
    const formData = new FormData();
    formData.append("file", file);
    const title = document.getElementById("upload-title").value.trim();
    if (title) formData.append("title", title);
    // No Content-Type header: the browser sets the multipart boundary.
    await api("/api/v1/documents", { method: "POST", body: formData });
    fileInput.value = "";
    document.getElementById("upload-title").value = "";
    await loadDocuments();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("vault", false);
  }
});

async function resyncDocument(id) {
  setBusy("vault", true);
  hideError();
  try {
    await api(`/api/v1/documents/${id}/resync`, { method: "POST" });
    await loadDocuments();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("vault", false);
  }
}

async function deleteDocument(id) {
  if (!window.confirm("¿Eliminar este documento y sus índices vectoriales?")) return;
  setBusy("vault", true);
  hideError();
  try {
    await api(`/api/v1/documents/${id}`, { method: "DELETE" });
    await loadDocuments();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("vault", false);
  }
}

// The append form is the two-session workflow in the UI: pick the document
// (its vault file), name the section, paste the text, append + re-index.
document.getElementById("append-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = document.getElementById("append-document").value;
  const text = document.getElementById("append-text").value.trim();
  if (!id || !text) return;
  const section = document.getElementById("append-section").value.trim();

  setBusy("vault", true);
  hideError();
  try {
    await api(`/api/v1/documents/${id}/append`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, section: section || null }),
    });
    document.getElementById("append-section").value = "";
    document.getElementById("append-text").value = "";
    await loadDocuments();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("vault", false);
  }
});

document.getElementById("documents-reload").addEventListener("click", loadDocuments);

// ---------------------------------------------------------------------------
// Tab 6: Mapa -> GET /api/v1/knowledge/map?topic=...
// ---------------------------------------------------------------------------

document.getElementById("map-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const topic = document.getElementById("map-topic").value.trim();
  if (!topic) return;

  setBusy("map", true);
  hideError();
  try {
    const data = await api(`/api/v1/knowledge/map?topic=${encodeURIComponent(topic)}`);
    document.getElementById("map-content").innerHTML = renderMd(data.map || "");
    document.getElementById("map-output").classList.remove("hidden");
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy("map", false);
  }
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

activateTab("chat");