"use strict";
/* Klasy dokumentów: list, edit, validate, try and save recipes through /api/recipes. Reuses helpers of app.js. */
const C = { current: null, readonly: false, protectedNames: [], errorLines: new Set(), deleteArmed: false };
const $c = {
  text: $("#recipe-text"), gutter: $("#recipe-gutter"), schema: $("#schema-text"),
  note: (n) => { $("#cnotice").replaceChildren(...(n ? [n] : [])); },
};
const cToast = (kind, title, body) => $c.note(title ? toast(kind, title, body) : null);
const classNameOf = (text) => ((text.match(/^class:\s*["']?([A-Za-z0-9_-]+)/m) || [])[1] || "");
const schemaFileOf = (text) => ((text.match(/^output_schema:\s*["']?([^\s"'#]+)/m) || [])[1] || "");

/* ---- Views: #przetwarzanie (default) and #klasy ---- */
function route() {
  const classes = location.hash === "#klasy";
  $("#view-process").hidden = classes;
  $("#view-classes").hidden = !classes;
  $("#nav-process").toggleAttribute("aria-current", !classes);
  $("#nav-classes").toggleAttribute("aria-current", classes);
  if (!classes) $("#nav-process").setAttribute("aria-current", "page");
  else { $("#nav-classes").setAttribute("aria-current", "page"); loadList(); }
  document.title = (classes ? "Klasy dokumentów · Ślad" : "Ślad · odwołania KIO do JSON") + " · Eterphis";
}
window.addEventListener("hashchange", route);

/* ---- List ---- */
async function loadList() {
  let j;
  try {
    const r = await fetch("/api/recipes");
    j = await r.json();
  } catch (_) {
    $("#class-list").replaceChildren(el("p", { class: "ct-body empty", text: "Nie udało się wczytać listy klas. Sprawdź, czy serwer działa, i odśwież stronę." }));
    return;
  }
  C.readonly = !!j.readonly; C.protectedNames = j.protected || [];
  $("#classes-note").textContent = j.recipes.length + " " + plural(j.recipes.length, "klasa", "klasy", "klas") + (C.readonly ? ", tryb tylko do odczytu" : "");
  $("#new-class").disabled = C.readonly;
  $("#class-list").replaceChildren(...j.recipes.map((r) =>
    el("article", { class: "ct-frame ct-frame--ice crow" + (r.error ? " crow--fault" : "") + (C.current && C.current.name === r.name ? " is-open" : "") },
      el("div", { class: "crow__main" },
        el("h3", { class: "ct-panel-title", text: r.name }),
        el("p", { class: "ct-cap", text: r.error ? r.error : (r.description || "Bez opisu") })),
      el("div", { class: "crow__tags" },
        r.error ? tag("fault", "Błąd receptury") : tag("live", r.fields + " " + plural(r.fields, "pole", "pola", "pól")),
        r.protected ? tag("arc", "Klasa zadania UZP") : null),
      el("button", { type: "button", class: "ct-btn ct-btn--sm ct-btn--ground", onclick: () => openEditor(r.name) }, el("span", { class: "ct-btn__face", text: C.readonly ? "Podgląd" : "Edytuj" })))));
}

/* ---- Editor ---- */
function paintGutter() {
  const n = $c.text.value.split("\n").length;
  const frag = [];
  for (let i = 1; i <= n; i++) frag.push(el("span", { class: C.errorLines.has(i) ? "bad" : "", text: String(i) }));
  $c.gutter.replaceChildren(...frag.flatMap((s) => [s, "\n"]));
  $c.gutter.scrollTop = $c.text.scrollTop;
}
$c.text.addEventListener("input", () => { paintGutter(); syncSchemaName(); });
$c.text.addEventListener("scroll", () => { $c.gutter.scrollTop = $c.text.scrollTop; });

function syncSchemaName() {
  const f = schemaFileOf($c.text.value);
  $("#schema-file").textContent = f ? "  " + f : "  (bez pliku: użyty zostanie schemas/<klasa>.json, jeśli istnieje)";
}

function setEditor({ name, text, schema, isNew, isProtected }) {
  C.current = { name, isNew, protected: isProtected };
  C.errorLines = new Set(); C.deleteArmed = false;
  $c.text.value = text; $c.schema.value = schema || "";
  paintGutter(); syncSchemaName(); showErrors([]);
  $c.note(null); $("#try-out").replaceChildren();
  $("#editor-sec").hidden = false;
  $("#editor-note").textContent = isNew ? "Nowa klasa z szablonu" : "Klasa: " + name;
  $("#btn-delete").hidden = isNew || isProtected || C.readonly;
  $("#btn-delete .ct-btn__face").textContent = "Usuń";
  $("#btn-save").disabled = C.readonly;
  $c.text.readOnly = C.readonly; $c.schema.readOnly = C.readonly;
  $("#recipe-msg").textContent = isProtected && !C.readonly
    ? "Klasa zadania UZP: można ją zmieniać, nie można usunąć. Poprzednia wersja zostaje w pliku .bak."
    : "Wzorce to wyrażenia regularne, dopasowywane do tekstu małymi literami bez polskich znaków.";
  $("#editor-sec").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
  loadList();
}

async function openEditor(name) {
  try {
    const r = await fetch("/api/recipes/" + encodeURIComponent(name));
    const j = await r.json();
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Serwer odrzucił zapytanie (" + r.status + ").");
    setEditor({ name, text: j.text, schema: j.output_schema && j.output_schema.text, isNew: false, isProtected: j.protected });
  } catch (e) {
    $("#editor-sec").hidden = false;
    cToast("fault", "Nie udało się otworzyć klasy " + name, e.message);
  }
}

$("#new-class").addEventListener("click", async () => {
  try {
    const j = await (await fetch("/api/recipe-template")).json();
    setEditor({ name: null, text: j.text, schema: j.output_schema, isNew: true, isProtected: false });
  } catch (_) {
    $("#editor-sec").hidden = false;
    cToast("fault", "Nie udało się wczytać szablonu", "Odśwież stronę i spróbuj ponownie.");
  }
});

/* ---- Errors: a list with line and JSON path; a click puts the caret on the line ---- */
function gotoLine(n) {
  const lines = $c.text.value.split("\n");
  let pos = 0;
  for (let i = 0; i < Math.min(n - 1, lines.length); i++) pos += lines[i].length + 1;
  $c.text.focus(); $c.text.setSelectionRange(pos, pos + (lines[n - 1] || "").length);
  const lh = parseFloat(getComputedStyle($c.text).lineHeight) || 20;
  $c.text.scrollTop = Math.max(0, (n - 4) * lh);
}
function showErrors(errors) {
  C.errorLines = new Set(errors.map((e) => e.line).filter(Boolean));
  paintGutter();
  const box = $("#errlist");
  box.hidden = errors.length === 0;
  box.replaceChildren(...errors.map((e) => {
    const where = (e.line ? "linia " + e.line + " · " : "") + e.path;
    const row = el("div", { class: "err" }, via("fault"),
      el("div", {}, el("p", { class: "err__where", text: where }), el("p", { class: "ct-body err__msg", text: e.message })));
    if (!e.line) return row;
    return el("button", { type: "button", class: "err err--go", "aria-label": "Przejdź do " + where, onclick: () => gotoLine(e.line) }, ...row.childNodes);
  }));
}
function reportErrors(res, what) {
  const errs = res.errors || [];
  showErrors(errs);
  cToast("fault", what + ": " + errs.length + " " + plural(errs.length, "błąd", "błędy", "błędów"),
    "Popraw zaznaczone linie. Każdy błąd podaje miejsce w pliku i co zmienić.");
}

/* ---- Actions ---- */
const draft = () => ({ text: $c.text.value, output_schema: $c.schema.value.trim() ? $c.schema.value : null });
async function api(url, opts) {
  const r = await fetch(url, opts);
  let j = null;
  try { j = await r.json(); } catch (_) {}
  return { r, j: j || {} };
}
function busy(btn, on, word) {
  const face = btn.querySelector(".ct-btn__face");
  if (on) { btn.dataset.word = face.textContent; face.textContent = word; btn.setAttribute("aria-busy", "true"); btn.disabled = true; }
  else { face.textContent = btn.dataset.word || face.textContent; btn.removeAttribute("aria-busy"); btn.disabled = btn.id === "btn-save" && C.readonly; }
}
function warnText(ws) { return ws && ws.length ? " " + ws.join(" ") : ""; }

$("#btn-validate").addEventListener("click", async () => {
  const b = $("#btn-validate"); busy(b, true, "Sprawdzam");
  try {
    const { r, j } = await api("/api/recipes/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft()) });
    if (!r.ok) throw new Error("Serwer odrzucił zapytanie (" + r.status + ").");
    if (j.ok) { showErrors([]); cToast("live", "Receptura jest poprawna", "Klasa " + j.class + ", " + j.fields + " " + plural(j.fields, "pole", "pola", "pól") + "." + warnText(j.warnings)); }
    else reportErrors(j, "Receptura nie przeszła sprawdzenia");
  } catch (e) { cToast("fault", "Nie udało się sprawdzić receptury", e.message); }
  finally { busy(b, false); }
});

$("#make-skeleton").addEventListener("click", async () => {
  const { r, j } = await api("/api/recipes/skeleton", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft()) });
  if (!r.ok) { reportErrors(j, "Nie da się zbudować szkieletu, bo receptura ma błędy"); return; }
  $c.schema.value = j.output_schema;
  cToast("live", "Szkielet zbudowany z pól", "Sprawdź go i dopisz pola, które mają być w wyniku nawet gdy nie ma ich w dokumencie.");
});

$("#btn-save").addEventListener("click", async () => {
  const name = classNameOf($c.text.value);
  if (!name) { showErrors([{ path: "class", line: 1, message: "Dopisz na początku pliku linię class: nazwa_klasy (małe litery, cyfry, podkreślenie)." }]); cToast("fault", "Brak nazwy klasy", "Dopisz linię class: nazwa_klasy na początku receptury."); return; }
  const b = $("#btn-save"); busy(b, true, "Zapisuję");
  try {
    const { r, j } = await api("/api/recipes/" + encodeURIComponent(name), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft()) });
    if (r.status === 422 && j.errors) { reportErrors(j, "Nic nie zapisano"); return; }
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Serwer odrzucił zapytanie (" + r.status + ").");
    showErrors([]);
    C.current = { name, isNew: false, protected: C.protectedNames.includes(name) };
    $("#editor-note").textContent = "Klasa: " + name;
    $("#btn-delete").hidden = C.current.protected || C.readonly;
    cToast("live", j.created ? "Dodano klasę " + name : "Zapisano klasę " + name, "Następny dokument zostanie rozpoznany według tej receptury, bez restartu." + warnText(j.warnings));
    loadList();
  } catch (e) { cToast("fault", "Nie udało się zapisać", e.message); }
  finally { busy(b, false); }
});

$("#btn-delete").addEventListener("click", async () => {
  const b = $("#btn-delete"), face = b.querySelector(".ct-btn__face");
  if (!C.current || C.current.isNew) return;
  if (!C.deleteArmed) {
    C.deleteArmed = true; face.textContent = "Potwierdź usunięcie";
    cToast("fault", "Usunąć klasę " + C.current.name + "?", "Plik receptury zostanie przeniesiony do " + C.current.name + ".yaml.bak. Kliknij jeszcze raz, aby potwierdzić.");
    return;
  }
  C.deleteArmed = false; face.textContent = "Usuń";
  const { r, j } = await api("/api/recipes/" + encodeURIComponent(C.current.name), { method: "DELETE" });
  if (!r.ok) { cToast("fault", "Nie udało się usunąć klasy", typeof j.detail === "string" ? j.detail : "Serwer odrzucił zapytanie (" + r.status + ")."); return; }
  const gone = C.current.name;
  C.current = null; $("#editor-sec").hidden = true;
  loadList();
  window.scrollTo({ top: 0, behavior: reduceMotion() ? "auto" : "smooth" });
  $("#class-list").before(el("div", { class: "notice", id: "dnotice" }, toast("live", "Usunięto klasę " + gone, "Plik został przeniesiony do " + j.backup + ". Przywrócisz go, zmieniając nazwę z powrotem na .yaml.")));
  setTimeout(() => { const n = $("#dnotice"); if (n) n.remove(); }, 8000);
});

/* ---- Try on PDF ---- */
$("#btn-try").addEventListener("click", () => $("#try-file").click());
$("#try-file").addEventListener("change", async (e) => {
  const picked = [...e.target.files]; e.target.value = "";
  if (!picked.length) return;
  const b = $("#btn-try"); busy(b, true, "Próbuję");
  const fd = new FormData();
  fd.append("text", $c.text.value);
  if ($c.schema.value.trim()) fd.append("output_schema", $c.schema.value);
  picked.forEach((f) => fd.append("files", f, f.name));
  try {
    const { r, j } = await api("/api/recipes/try", { method: "POST", body: fd });
    if (r.status === 422 && j.errors) { reportErrors(j, "Nie da się wypróbować"); return; }
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Serwer odrzucił zapytanie (" + r.status + ").");
    showErrors([]);
    const n = j.documents.length, hit = j.documents.filter((d) => d.matched).length;
    cToast(hit === n ? "live" : "arc", "Wypróbowano na " + n + " " + plural(n, "pliku", "plikach", "plikach"),
      hit + " z " + n + " rozpoznanych jako " + j.class + ". Nic nie zostało zapisane." + warnText(j.warnings));
    $("#try-out").replaceChildren(...j.documents.map((d, i) => tryCard(d, j.class, i)));
    $("#try-out").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
  } catch (err) { cToast("fault", "Nie udało się wypróbować receptury", err.message); }
  finally { busy(b, false); }
});

function tryCard(d, cls, i) {
  if (d.error) return el("article", { class: "ct-frame ct-frame--ice ct-panel doc doc--rejected" },
    tag("fault", "Błąd"), el("h3", { class: "ct-panel-title", text: d.input_name }), el("p", { class: "ct-body", text: d.error }));
  const c = d.classification;
  const entries = Object.entries(c.scores || {}).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map((e) => e[1]));
  const scores = el("div", { class: "scores", role: "group", "aria-label": "Wyniki dla poszczególnych klas" },
    entries.map(([k, v]) => el("div", { class: "srow" },
      el("span", { class: "k", text: k === cls ? k + " (szkic)" : k }),
      trace(v / max, k === cls ? (d.matched ? "top" : "arc") : ""),
      el("span", { class: "n", text: fmtNum(v) }))));
  const head = el("div", { class: "doc__head" },
    el("div", { class: "doc__title" },
      d.matched ? tag("live", "Rozpoznany jako " + cls) : tag("fault", "Nie rozpoznany jako " + cls),
      el("h3", { class: "ct-panel-title", text: d.input_name }),
      el("p", { class: "doc__file", text: d.matched ? "Pola poniżej wyciągnięto według szkicu." : "Wygrała: " + (c.doc_class || "żadna klasa") + ". Pola poniżej wyciągnięto mimo to, żebyś mógł poprawić receptury." })),
    el("div", { class: "doc__score" }, el("span", { class: "ct-readout", text: fmtNum(d.draft_score) }), el("span", { class: "ct-cap", text: "wynik szkicu" })));
  const reason = el("div", { class: "doc__reason" }, el("p", { class: "ct-label", text: "Dlaczego" }), el("p", { class: "ct-body", text: c.reason || "brak opisu" }));
  const filled = Object.keys(d.evidence).length;
  return el("article", { class: "ct-frame ct-frame--ice ct-panel doc" },
    head, reason, scores,
    el("h4", { class: "ct-h", text: "Pola i dowody (" + filled + ")" }),
    evidenceTable(d.evidence),
    el("h4", { class: "ct-h", text: "Wynik JSON" }),
    el("div", { class: "ct-frame ct-frame--well json-box" }, el("pre", { class: "json ct-bar", tabindex: "0", role: "region", "aria-label": "JSON próby " + d.input_name, text: pretty(d.data) })));
}

route();
