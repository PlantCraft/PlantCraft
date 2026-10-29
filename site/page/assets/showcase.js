// The clips at the top of the page: one video, and under it a pause button, a bar to click or
// drag, and one button per part of the suite whose fill shows how far its clip has played. The
// clips play one after the other; picking one, dragging the bar or pausing stops that. With
// reduced motion nothing plays until the visitor presses play.
(() => {
  const v = document.querySelector(".showcase video");
  const tabs = [...document.querySelectorAll(".clip-tabs button")];
  if (!v || !tabs.length) return;
  const play = document.querySelector(".clip-play");
  const seek = document.querySelector(".clip-seek");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let current = 0;
  let auto = !still;
  let dragging = false;
  let resume = false;

  const at = () => (v.duration ? v.currentTime / v.duration : 0);

  function paint() {
    play.classList.toggle("paused", v.paused);
    play.setAttribute("aria-label", v.paused ? "Play" : "Pause");
    if (!dragging) seek.value = String(Math.round(at() * 1000));
    seek.style.setProperty("--at", `${seek.value / 10}%`);
    tabs.forEach((tab, j) => {
      const fill = j < current && auto ? 1 : j === current ? seek.value / 1000 : 0;
      tab.style.setProperty("--fill", `${fill * 100}%`);
    });
  }

  function show(i, start) {
    current = i;
    const t = tabs[i];
    tabs.forEach((tab, j) => tab.setAttribute("aria-pressed", String(j === i)));
    v.poster = t.dataset.poster;
    v.setAttribute("aria-label", t.dataset.label);
    const [webm, mp4] = v.querySelectorAll("source");
    webm.src = t.dataset.webm;
    mp4.src = t.dataset.mp4;
    v.load();
    if (start) v.play().catch(() => {});
    paint();
  }

  tabs.forEach((tab, i) => tab.addEventListener("click", () => { auto = false; show(i, true); }));
  ["play", "pause", "timeupdate", "loadedmetadata", "seeked"].forEach((ev) => v.addEventListener(ev, paint));
  v.addEventListener("ended", () => {
    if (auto) show((current + 1) % tabs.length, true);
    else { v.currentTime = 0; v.play().catch(() => {}); }
  });

  play.addEventListener("click", () => {
    if (v.paused) v.play().catch(() => {});
    else { auto = false; v.pause(); }
  });
  // Dragging pauses the clip, so the frame follows the dot; letting go plays on from there.
  seek.addEventListener("pointerdown", () => {
    dragging = true;
    auto = false;
    resume = !v.paused;
    v.pause();
  });
  const release = () => {
    if (!dragging) return;
    dragging = false;
    if (resume) v.play().catch(() => {});
  };
  addEventListener("pointerup", release);
  addEventListener("pointercancel", release);
  seek.addEventListener("input", () => {
    auto = false;
    if (v.duration) v.currentTime = (seek.value / 1000) * v.duration;
    paint();
  });
  const tick = () => { if (!v.paused) paint(); requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  show(0, !still);
})();
