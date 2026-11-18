const windowEl = document.getElementById("chat-window");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const sendBtn = document.getElementById("chat-send");
const starters = document.getElementById("starters");
const showProjects = document.getElementById("show-projects");
const MORE = [["architecture", "More on the architecture"], ["strengths", "More on the strengths"],
              ["intelligence", "More on the intelligence"]];
let currentProject = null;     // the project of the last brief or answer, sent with every question
let busy = false;

// --- rendering: a small Markdown subset built from DOM nodes; text is never parsed as HTML ---

function inline(parent, text) {
  for (const part of text.split(/(\*\*[^*]+\*\*|`[^`]+`)/)) {
    if (!part) continue;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      const el = document.createElement("strong");
      el.textContent = part.slice(2, -2);
      parent.appendChild(el);
    } else if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      const el = document.createElement("code");
      el.textContent = part.slice(1, -1);
      parent.appendChild(el);
    } else {
      parent.appendChild(document.createTextNode(part));
    }
  }
}

function render(text) {
  const out = document.createDocumentFragment();
  let list = null;
  let para = null;
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (!line.trim()) { list = null; para = null; continue; }
    if (heading) {
      const el = heading[1].length === 1 ? document.createElement("h2") : document.createElement("h3");
      inline(el, heading[2]);
      out.appendChild(el);
      list = null; para = null;
    } else if (bullet) {
      if (!list) { list = document.createElement("ul"); out.appendChild(list); }
      const li = document.createElement("li");
      inline(li, bullet[1]);
      list.appendChild(li);
      para = null;
    } else {
      if (!para) { para = document.createElement("p"); out.appendChild(para); }
      else para.appendChild(document.createTextNode(" "));
      inline(para, line.trim());
      list = null;
    }
  }
  return out;
}

// --- the conversation ---

function show(el) {
  windowEl.appendChild(el);
  el.scrollIntoView({ block: "nearest" });
  return el;
}

function addMessage(text, cls) {
  const el = document.createElement("div");
  el.className = `msg ${cls}`;
  el.textContent = text;
  return show(el);
}

function addAnswer() {
  const el = document.createElement("div");
  el.className = "msg msg-bot msg-rich";
  return show(el);
}

// Three dots until the first words arrive; screen readers hear one short line instead.
function addTyping() {
  const el = document.createElement("div");
  el.className = "msg msg-pending";
  const dots = document.createElement("span");
  dots.className = "typing";
  dots.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 3; i++) dots.appendChild(document.createElement("i"));
  const label = document.createElement("span");
  label.className = "visually-hidden";
  label.textContent = "Chat is typing";
  const hint = document.createElement("span");
  hint.className = "typing-hint";
  hint.setAttribute("aria-hidden", "true");
  hint.textContent = "A small model on a small server: an answer can take up to a minute.";
  el.append(dots, label, hint);
  return show(el);
}

// Under a project answer: deeper questions for the model, and the checked brief the answer was written from.
function addFollowUps(project, withMore) {
  const row = document.createElement("div");
  row.className = "more";
  const add = (label, body) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "more-btn";
    button.textContent = label;
    button.addEventListener("click", () => ask(body, button));
    row.appendChild(button);
  };
  if (withMore) for (const [section, label] of MORE) add(label, { message: label, project, section, detail: true });
  add("Show the checked brief", { message: "Show the checked brief", project, brief: true });
  show(row);
}

function foldProjects() {
  document.querySelector(".chat-shell").classList.add("chatting");
  if (!starters || starters.hidden) return;
  starters.hidden = true;
  showProjects.hidden = false;
  showProjects.setAttribute("aria-expanded", "false");
}

if (showProjects) {
  showProjects.addEventListener("click", () => {
    starters.hidden = !starters.hidden;
    showProjects.setAttribute("aria-expanded", String(!starters.hidden));
  });
}

// --- asking: the answer arrives as NDJSON lines (text chunks, replace, error, then done) ---

// While an answer is coming every way to ask is disabled, and the conversation is marked busy so screen readers
// read the answer once it is complete instead of after every chunk.
function setBusy(state) {
  busy = state;
  input.disabled = state;
  sendBtn.disabled = state;
  document.querySelectorAll(".starter, .more-btn").forEach((button) => { button.disabled = state; });
  if (state) windowEl.setAttribute("aria-busy", "true");
  else windowEl.removeAttribute("aria-busy");
}

// `from` is the button that asked; a typed question returns focus to the input, a button keeps it (no keyboard
// popping up on phones, no jump back to the top).
async function ask(body, from) {
  if (busy) return;
  setBusy(true);
  foldProjects();
  addMessage(body.message, "msg-user");
  let pending = addTyping();
  let bubble = null;
  let text = "";
  let errorShown = false;
  const paint = () => {
    if (pending) { pending.remove(); pending = null; }
    if (!bubble) bubble = addAnswer();
    bubble.replaceChildren(render(text));
    bubble.scrollIntoView({ block: "nearest" });
  };

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: currentProject, ...body }),
    });
    if (!res.ok) {
      let detail = "Something went wrong. Try again in a minute.";
      try {
        const data = await res.json();
        if (typeof data.detail === "string") detail = data.detail;
      } catch (_) { /* keep the default */ }
      if (pending) pending.remove();
      addMessage(detail, "msg-error");
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let done = null;
    for (;;) {
      const { value, done: end } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !end });
      let cut;
      while ((cut = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, cut).trim();
        buffer = buffer.slice(cut + 1);
        if (!line) continue;
        const msg = JSON.parse(line);
        if (typeof msg.text === "string") { text += msg.text; paint(); }
        else if (typeof msg.replace === "string") { text = msg.replace; paint(); }
        else if (typeof msg.error === "string") {
          if (pending) { pending.remove(); pending = null; }
          addMessage(msg.error, "msg-error");
          errorShown = true;
        } else if (msg.done) done = msg;
      }
      if (end) break;
    }
    if (pending) pending.remove();
    if (!text && !errorShown) addMessage("No answer came back. Try again in a minute.", "msg-error");
    if (done && done.project) currentProject = done.project;
    if (done && done.grounded && done.project && text) addFollowUps(done.project, !body.section);
  } catch (err) {
    if (pending) pending.remove();
    addMessage("The model could not be reached. Check your connection and try again.", "msg-error");
  } finally {
    setBusy(false);
    if (!from) input.focus();
    else if (from.isConnected && from.offsetParent) from.focus({ preventScroll: true });
  }
}

document.querySelectorAll(".starter").forEach((button) => {
  button.addEventListener("click", () => {
    ask({ message: button.textContent, project: button.dataset.project }, button);
  });
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  ask({ message });
});
