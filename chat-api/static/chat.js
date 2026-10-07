const windowEl = document.getElementById("chat-window");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const sendBtn = document.getElementById("chat-send");
const starters = document.getElementById("starters");

document.querySelectorAll(".starter").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.textContent;
    form.requestSubmit();
  });
});

function show(el) {
  windowEl.appendChild(el);
  el.scrollIntoView({ block: "end" });        // scroll-margin keeps it above the composer
  return el;
}

function addMessage(text, cls) {
  const el = document.createElement("div");
  el.className = `msg ${cls}`;
  el.textContent = text;                       // replies are text, never markup
  return show(el);
}

// Three dots while the model answers; screen readers hear one short line instead.
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
  el.append(dots, label);
  return show(el);
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  if (starters) starters.remove();
  addMessage(message, "msg-user");
  input.value = "";
  input.disabled = true;
  sendBtn.disabled = true;
  const pending = addTyping();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    pending.remove();
    if (!res.ok) {
      let detail = "Something went wrong. Try again in a minute.";
      try { detail = (await res.json()).detail || detail; } catch (_) { /* keep the default */ }
      addMessage(detail, "msg-error");
    } else {
      const data = await res.json();
      addMessage(data.reply, "msg-bot");
    }
  } catch (err) {
    pending.remove();
    addMessage("The model could not be reached. Check your connection and try again.", "msg-error");
  } finally {
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
  }
});
