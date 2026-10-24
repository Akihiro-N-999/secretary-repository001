const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const quickBtns = document.querySelectorAll(".quick button");

let conversationId = null;
let busy = false;

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderMarkdown(text) {
  // CDN が読めない環境では Markdown を整形せずそのまま表示する
  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    return `<div style="white-space: pre-wrap">${escapeHtml(text)}</div>`;
  }
  return DOMPurify.sanitize(marked.parse(text));
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addMessage(role) {
  messagesEl.querySelector(".welcome")?.remove();
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  return wrap;
}

function setBusy(value) {
  busy = value;
  sendBtn.disabled = value;
  quickBtns.forEach((b) => (b.disabled = value));
}

// サーバーから届く SSE (data: {...}\n\n) を1イベントずつ取り出す
async function* readEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (chunk.startsWith("data: ")) yield JSON.parse(chunk.slice(6));
    }
  }
}

async function send(text) {
  if (busy || !text.trim()) return;
  setBusy(true);

  addMessage("user").querySelector(".bubble").textContent = text;
  const reply = addMessage("assistant");
  const bubble = reply.querySelector(".bubble");
  const status = document.createElement("div");
  status.className = "status";
  status.textContent = "考えています";
  reply.appendChild(status);
  scrollToBottom();

  let markdown = "";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, message: text }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    for await (const ev of readEvents(res)) {
      if (ev.type === "conversation") {
        conversationId = ev.id;
      } else if (ev.type === "text") {
        markdown += ev.text;
        bubble.innerHTML = renderMarkdown(markdown);
        status.textContent = "回答を作成中";
      } else if (ev.type === "status") {
        status.textContent = ev.text;
      } else if (ev.type === "error") {
        const err = document.createElement("div");
        err.className = "error";
        err.textContent = ev.text;
        reply.appendChild(err);
      }
      scrollToBottom();
    }
  } catch (e) {
    const err = document.createElement("div");
    err.className = "error";
    err.textContent = `通信エラー: ${e.message}`;
    reply.appendChild(err);
  } finally {
    status.remove();
    if (!markdown) bubble.remove();
    setBusy(false);
    loadWatchlist(); // 会話の中でウォッチリストが変わることがある
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value;
  input.value = "";
  send(text);
});

input.addEventListener("keydown", (e) => {
  // Enter で送信、Shift+Enter で改行 (日本語入力の変換確定中は送信しない)
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    form.requestSubmit();
  }
});

quickBtns.forEach((btn) => btn.addEventListener("click", () => send(btn.dataset.prompt)));

document.getElementById("new-chat").addEventListener("click", async () => {
  if (busy) return;
  if (conversationId) {
    await fetch(`/api/conversations/${conversationId}`, { method: "DELETE" });
  }
  conversationId = null;
  messagesEl.innerHTML = '<div class="welcome"><p>新しい会話を始めます。何をお調べしましょうか。</p></div>';
});

// ---- ウォッチリスト ----
const watchlistEl = document.getElementById("watchlist");
const watchForm = document.getElementById("watch-form");

async function loadWatchlist() {
  const res = await fetch("/api/watchlist");
  const items = await res.json();
  watchlistEl.innerHTML = "";
  if (items.length === 0) {
    watchlistEl.innerHTML = '<li class="note">まだ銘柄がありません</li>';
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    const info = document.createElement("div");
    info.className = "info";
    const sym = document.createElement("div");
    sym.className = "sym";
    sym.textContent = item.symbol;
    info.appendChild(sym);
    if (item.note) {
      const note = document.createElement("div");
      note.className = "note";
      note.textContent = item.note;
      info.appendChild(note);
    }
    const ask = document.createElement("button");
    ask.className = "ask";
    ask.textContent = "調べる";
    ask.title = "この銘柄について聞く";
    ask.addEventListener("click", () =>
      send(`${item.symbol} について、現在の株価、直近1か月の値動き、最近のニュースをまとめてください。`)
    );
    const remove = document.createElement("button");
    remove.className = "remove";
    remove.textContent = "×";
    remove.title = "削除";
    remove.addEventListener("click", async () => {
      await fetch(`/api/watchlist/${encodeURIComponent(item.symbol)}`, { method: "DELETE" });
      loadWatchlist();
    });
    li.append(info, ask, remove);
    watchlistEl.appendChild(li);
  }
}

watchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const symbol = document.getElementById("watch-symbol");
  const note = document.getElementById("watch-note");
  await fetch("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: symbol.value, note: note.value }),
  });
  symbol.value = "";
  note.value = "";
  loadWatchlist();
});

loadWatchlist();
