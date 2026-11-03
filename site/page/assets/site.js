// Every page: the phone menu, links to other sites in a new tab, the contact forms (sent to
// /api/contact like the chat's) and the install page's system tabs. No library, no cookie.
(() => {
  const $$ = (s) => [...document.querySelectorAll(s)];
  const burger = document.querySelector(".burger");
  if (burger) burger.addEventListener("click", () => {
    const open = document.body.classList.toggle("mopen");
    burger.setAttribute("aria-expanded", String(open));
  });
  $$("nav a, .mmenu a").forEach((a) => {
    const here = location.pathname.split("/").pop() || "index.html";
    if (a.getAttribute("href") === here || (here === "index.html" && a.getAttribute("href") === "./")) a.classList.add("cur");
  });
  $$('a[href^="http"]').forEach((a) => { a.target = "_blank"; a.rel = "noopener"; });
  $$(".ostab").forEach((b) => b.addEventListener("click", () => {
    $$(".ostab, .ost").forEach((e) => e.classList.toggle("on", e.dataset.o === b.dataset.o));
  }));

  $$("form.form").forEach((form) => form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = form.elements;
    const status = form.querySelector("[role=status]");
    const extra = [...form.querySelectorAll("[data-label]")]
      .map((e) => `${e.dataset.label} ${e.value.trim()}`).join("\n");
    const data = {
      name: (f.name?.value || "").trim(),
      email: (f.email?.value || "").trim(),
      company: (f.company?.value || "").trim(),
      need: `${form.dataset.form}\n${extra}`.trim(),
      website: f.website?.value || "",
      conversation: [],
    };
    const empty = [...form.querySelectorAll("[required]")].some((e) => !e.value.trim());
    if (empty || !/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(data.email)) {
      status.className = "fnote err";
      status.textContent = "Fill in every field and a valid e-mail.";
      return;
    }
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    fetch("api/contact", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(data),
    })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        form.reset();
        status.className = "fnote ok";
        status.textContent = `Thank you, ${data.name}. We will write to ${data.email}.`;
      })
      .catch(() => {
        status.className = "fnote err";
        status.textContent = "Could not send now. Try again later, or write to info@plantcraft.io.";
      })
      .finally(() => { button.disabled = false; });
  }));
})();
