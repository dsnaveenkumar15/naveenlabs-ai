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

function addMessage(text, cls) {
  const el = document.createElement("div");
  el.className = `msg ${cls}`;
  el.textContent = text;
  windowEl.appendChild(el);
  windowEl.scrollTop = windowEl.scrollHeight;
  return el;
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
  const pending = addMessage("Thinking…", "msg-pending");

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
