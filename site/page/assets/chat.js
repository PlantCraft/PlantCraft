// The site's chat: questions go to /api/chat (answered from the public documentation), contact
// requests to /api/contact. No library, no cookie; the conversation lives in this tab only.
(function () {
  "use strict";
  var panel, log, form, input, contact, launch, include;
  var messages = [];
  var assistant = null; // null: not asked yet; then true or false
  var busy = false;
  var KEY = "plantcraft-chat";
  var STARTERS = [
    "What is PlantCraft?",
    "What does it cost?",
    "Does it need the internet or a cloud AI?",
    "Can it write to our DCS?",
    "What server do I need?",
  ];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function esc(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function safeUrl(u) {
    return /^https:\/\/[^\s"'<>]+$/.test(u || "") ? u : null;
  }

  // The model writes short paragraphs, "- " bullets, **bold** and [n] citations; nothing else
  // becomes markup, and everything is escaped first.
  function format(text, sources) {
    function inline(s) {
      s = esc(s).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      return s.replace(/\[(\d{1,2})\]/g, function (m, n) {
        var src = sources[Number(n) - 1];
        var url = src && safeUrl(src.url);
        if (!url) return "";
        return '<sup><a href="' + esc(url) + '" target="_blank" rel="noopener" title="' + esc(src.title) + '">' + n + "</a></sup>";
      });
    }
    var html = "";
    text.split(/\n{2,}/).forEach(function (block) {
      var lines = block.split("\n");
      if (lines.every(function (l) { return /^\s*[-*•]\s+/.test(l) || !l.trim(); })) {
        html += "<ul>" + lines.filter(function (l) { return l.trim(); }).map(function (l) {
          return "<li>" + inline(l.replace(/^\s*[-*•]\s+/, "")) + "</li>";
        }).join("") + "</ul>";
      } else {
        html += "<p>" + lines.map(inline).join("<br>") + "</p>";
      }
    });
    return html;
  }

  function scroll() { log.scrollTop = log.scrollHeight; }

  function bot(html, opts) {
    var node = el("div", "msg bot");
    node.innerHTML = html;
    opts = opts || {};
    if (opts.sources && opts.sources.length) {
      var list = el("ol", "srcs");
      opts.sources.forEach(function (s, i) {
        var url = safeUrl(s.url);
        if (!url) return;
        var li = el("li");
        var a = el("a", null, (i + 1) + ". " + s.title);
        a.href = url; a.target = "_blank"; a.rel = "noopener";
        li.appendChild(a); list.appendChild(li);
      });
      node.appendChild(list);
    }
    if (opts.contact) {
      var b = el("button", "btn small primary cta", "Leave your contact");
      b.type = "button";
      b.addEventListener("click", function () { show("contact"); });
      node.appendChild(b);
    }
    log.appendChild(node);
    scroll();
    return node;
  }

  function user(text) {
    log.appendChild(el("div", "msg user", text));
    scroll();
  }

  function save() {
    try { sessionStorage.setItem(KEY, JSON.stringify(messages.slice(-20))); } catch (e) { /* private mode */ }
  }

  function intro() {
    if (assistant === false) {
      bot("<p>Leave your contact and what you need, and the team will write back to you.</p>");
      return;
    }
    bot("<p>Hi! I answer questions about PlantCraft from its public documentation. For anything else, I can put you in touch with the team.</p>");
    var chips = el("div", "chips");
    STARTERS.forEach(function (q) {
      var c = el("button", "chip", q);
      c.type = "button";
      c.addEventListener("click", function () { chips.remove(); ask(q); });
      chips.appendChild(c);
    });
    log.appendChild(chips);
  }

  function restore() {
    var old = [];
    try { old = JSON.parse(sessionStorage.getItem(KEY) || "[]"); } catch (e) { old = []; }
    if (!Array.isArray(old) || !old.length) return false;
    old.forEach(function (m) {
      if (m && m.role === "user") user(m.content);
      else if (m && m.role === "assistant") bot(format(m.content, m.sources || []), { sources: m.sources });
    });
    messages = old;
    return true;
  }

  function status() {
    return fetch("api/chat/status", { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : { assistant: false }; })
      .then(function (d) { assistant = !!d.assistant; })
      .catch(function () { assistant = false; });
  }

  function show(mode) {
    var isContact = mode === "contact";
    contact.hidden = !isContact;
    form.hidden = isContact || assistant === false;
    log.hidden = isContact;
    panel.classList.toggle("contact-mode", isContact);
    include.hidden = !messages.some(function (m) { return m.role === "user"; });
    (isContact ? contact.querySelector("input[name=name]") : input).focus();
    if (!isContact) scroll();
  }

  function open(mode) {
    panel.hidden = false;
    launch.setAttribute("aria-expanded", "true");
    var ready = assistant === null ? status() : Promise.resolve();
    ready.then(function () {
      if (!log.childNodes.length && !restore()) intro();
      show(mode === "contact" || assistant === false ? "contact" : "chat");
    });
  }

  function close() {
    panel.hidden = true;
    launch.setAttribute("aria-expanded", "false");
    launch.focus();
  }

  function ask(text) {
    text = text.trim();
    if (!text || busy) return;
    busy = true;
    user(text);
    messages.push({ role: "user", content: text });
    var wait = bot("<p>Looking in the documentation…</p>");
    wait.classList.add("wait");
    var history = messages.map(function (m) { return { role: m.role, content: m.content }; });
    fetch("api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ messages: history.slice(-12) }),
    })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (d) {
        wait.remove();
        if (d.assistant === false) {
          assistant = false;
          bot("<p>The assistant is not available right now. Leave your contact and the team will answer you.</p>", { contact: true });
          return;
        }
        var answer = d.answer || "Something went wrong. Try again, or leave your contact.";
        var sources = Array.isArray(d.sources) ? d.sources : [];
        bot(format(answer, sources), { sources: sources, contact: !!d.contact });
        if (d.answer) { messages.push({ role: "assistant", content: answer, sources: sources }); }
        save();
      })
      .catch(function () {
        wait.remove();
        bot("<p>The site could not be reached. Try again in a moment.</p>", { contact: true });
      })
      .finally(function () { busy = false; });
  }

  function sendContact(ev) {
    ev.preventDefault();
    var f = contact.elements;
    var err = document.getElementById("chat-contact-error");
    var data = {
      name: f.name.value.trim(), email: f.email.value.trim(), company: f.company.value.trim(),
      need: f.need.value.trim(), website: f.website.value,
      conversation: f.include.checked && !include.hidden
        ? messages.filter(function (m) { return m.role === "user"; }).map(function (m) { return m.content; }).slice(-12)
        : [],
    };
    if (!data.name || !data.need || !/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(data.email)) {
      err.textContent = "Fill in your name, a valid email and what you need.";
      return;
    }
    err.textContent = "";
    var button = contact.querySelector("button[type=submit]");
    button.disabled = true;
    fetch("api/contact", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(data),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) { err.textContent = res.d.error === "check the form" ? "Check the fields of the form." : "Could not send now. Try again later."; return; }
        contact.reset();
        if (assistant === false && !log.childNodes.length) intro();
        bot("<p>Thank you, " + esc(data.name) + ". The team will write to <strong>" + esc(data.email) + "</strong>.</p>");
        show("chat");
        if (assistant === false) { log.hidden = false; contact.hidden = true; panel.classList.remove("contact-mode"); }
      })
      .catch(function () { err.textContent = "Could not send now. Try again later."; })
      .finally(function () { button.disabled = false; });
  }

  document.addEventListener("DOMContentLoaded", function () {
    panel = document.getElementById("chat");
    log = document.getElementById("chat-log");
    form = document.getElementById("chat-form");
    input = document.getElementById("chat-q");
    contact = document.getElementById("chat-contact");
    include = document.getElementById("chat-include");
    launch = document.querySelector(".chat-launch");
    document.querySelectorAll("[data-chat]").forEach(function (b) {
      b.addEventListener("click", function () { open(b.getAttribute("data-chat")); });
    });
    panel.querySelector("[data-chat-close]").addEventListener("click", close);
    contact.querySelector("[data-chat-back]").addEventListener("click", function () {
      if (assistant === false) { close(); return; }
      show("chat");
    });
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var q = input.value;
      input.value = "";
      input.style.height = "";
      ask(q);
    });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); form.requestSubmit(); }
    });
    input.addEventListener("input", function () {
      input.style.height = "";
      input.style.height = Math.min(input.scrollHeight, 120) + "px";
    });
    contact.addEventListener("submit", sendContact);
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !panel.hidden) close();
    });
  });
})();
