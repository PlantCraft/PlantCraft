// PlantCraft: says that Python is starting in this browser while the notebook's kernel starts
// (notebooks/build.py adds this file to JupyterLab's page). JupyterLab itself shows it only as a
// word in the status bar; the first start also downloads Python, which takes a while.
(function () {
  "use strict";
  var STARTING = /Python \(Pyodide\) \| (Starting|Initializing|Connecting|Restarting|Unknown|No Kernel)/;
  var READY = /Python \(Pyodide\) \| (Idle|Busy)/;
  var banner = null;
  var seenReady = false;

  function show() {
    if (banner) return;
    banner = document.createElement("div");
    banner.id = "plantcraft-python-starting";
    banner.setAttribute("role", "status");
    banner.style.cssText = "position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:10000;" +
      "background:#1d4ed8;color:#fff;padding:10px 16px;border-radius:8px;font:14px system-ui,sans-serif;" +
      "box-shadow:0 4px 16px rgba(0,0,0,.25);max-width:90vw";
    banner.textContent = seenReady
      ? "Starting Python on your computer…"
      : "Starting Python on your computer… The first time in this browser it can take up to a minute.";
    document.body.appendChild(banner);
  }

  function hide() {
    if (banner) { banner.remove(); banner = null; }
  }

  function check() {
    var text = "";
    var items = document.querySelectorAll(".jp-StatusBar-Item, .jp-StatusBar-TextItem");
    for (var i = 0; i < items.length; i++) text += " " + (items[i].textContent || "");
    if (READY.test(text)) { seenReady = true; hide(); }
    else if (STARTING.test(text)) show();
    else hide();
  }

  // Where this notebook runs, always in sight (owner, 2026-10-26): in this browser, with its edits
  // kept here; the kit's JupyterLab on the person's computer says the same about itself.
  function place() {
    if (document.getElementById("plantcraft-where") || !document.body) return;
    var pill = document.createElement("div");
    pill.id = "plantcraft-where";
    pill.setAttribute("role", "note");
    pill.title = "Python runs inside this browser, on your computer. What you change is kept in this browser only: File > Download keeps a copy.";
    pill.style.cssText = "position:fixed;top:4px;right:12px;z-index:9999;pointer-events:auto;" +
      "background:rgba(29,78,216,.1);color:inherit;border:1px solid rgba(29,78,216,.35);" +
      "padding:2px 10px;border-radius:999px;font:12px system-ui,sans-serif;white-space:nowrap";
    pill.textContent = "In this browser \u00b7 changes stay in this browser";
    document.body.appendChild(pill);
  }

  window.setInterval(function () { place(); check(); }, 500);
})();
