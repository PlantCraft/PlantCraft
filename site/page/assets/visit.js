// How many people read the site and for how long, without a cookie: this page view gets a random
// id that lives in this tab only, and tells /api/visit it is still open every 30 seconds while it
// is in front, and which button or link was clicked (its words and where it goes, nothing typed).
// The server keeps no address (site/sitechat/visits.py).
(function () {
  "use strict";
  if (!window.fetch) return;
  var id = Math.random().toString(36).slice(2) + Date.now().toString(36);
  var ref = "";
  try {
    var from = document.referrer ? new URL(document.referrer).hostname : "";
    if (from && from !== location.hostname) ref = from;
  } catch (e) {}

  function send(first, click) {
    var body = { id: id };
    if (first) body = { id: id, page: location.pathname, ref: ref };
    if (click) body.click = click;
    body = JSON.stringify(body);
    try {
      fetch("api/visit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
        keepalive: true,
      }).catch(function () {});
    } catch (e) {}
  }

  send(true);
  document.addEventListener(
    "click",
    function (event) {
      var target = event.target && event.target.closest ? event.target.closest("a, button") : null;
      if (!target) return;
      var words = (target.getAttribute("aria-label") || target.textContent || "")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 60);
      var href = target.getAttribute("href") || "";
      var to = "";
      if (href.charAt(0) === "#") to = href;
      else if (href) {
        try {
          var url = new URL(href, location.href);
          to = url.hostname === location.hostname ? url.pathname : url.hostname + url.pathname;
        } catch (e) {}
      }
      if (words || to) send(false, (words + (to ? " → " + to : "")).slice(0, 200));
    },
    true
  );
  setInterval(function () {
    if (document.visibilityState === "visible") send(false);
  }, 30000);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") send(false);
  });
})();
