const windowEl = document.getElementById("chat-window");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const sendBtn = document.getElementById("chat-send");

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

  addMessage(message, "msg-user");
  input.value = "";
  input.disabled = true;
  sendBtn.disabled = true;
  const pending = addMessage("thinking…", "msg-pending");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    pending.remove();
    if (res.status === 429) {
      addMessage("Rate limit hit — wait a minute before trying again.", "msg-error");
    } else if (!res.ok) {
      addMessage("Something went wrong. Try again shortly.", "msg-error");
    } else {
      const data = await res.json();
      addMessage(data.reply, "msg-bot");
    }
  } catch (err) {
    pending.remove();
    addMessage("Couldn't reach the model. Try again shortly.", "msg-error");
  } finally {
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
  }
});
