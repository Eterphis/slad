"use strict";
const $ = (s) => document.querySelector(s);
const SVGNS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;  // absent attribute, not the string "null"
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) n.append(c);
  return n;
};
const CLASS_PL = { odwolanie: "Odwołanie", pelnomocnictwo: "Pełnomocnictwo", przelew: "Potwierdzenie przelewu" };
const fmtNum = (x) => (Math.round(x * 100) / 100).toString().replace(".", ",");
const pretty = (o) => JSON.stringify(o, null, 2);
const reduceMotion = () => window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
const plural = (n, one, few, many) => (n === 1 ? one : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? few : many);

let files = [];
let last = null;

/* ---- Colour mode: night by default, the Daylight switch stores the choice ---- */
const modeSwitch = $("#mode-switch");
modeSwitch.setAttribute("aria-checked", String(document.documentElement.dataset.theme === "light"));
modeSwitch.addEventListener("ct-switch", (e) => window.ColdTrace.setTheme(e.detail.checked ? "light" : "dark"));

/* ---- Kit pieces ---- */
const via = (kind) => el("i", { class: "ct-v" + (kind ? " ct-v--" + kind : ""), "aria-hidden": "true" });
const tag = (kind, text) => el("span", { class: "ct-tag" + (kind ? " ct-tag--" + kind : "") }, via(kind), text);
const key = (text, { kind = "", id, onclick, icon, title } = {}) =>
  el("button", { type: "button", class: "ct-btn" + (kind ? " ct-btn--" + kind : ""), id: id || null, onclick, title: title || null, "aria-label": title || null },
    el("span", { class: "ct-btn__face" }, icon || null, text));
const icon = (d) => {
  const s = document.createElementNS(SVGNS, "svg");
  s.setAttribute("class", "ct-icon"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(SVGNS, "path"); p.setAttribute("d", d); s.append(p);
  return s;
};
function trace(frac, kind) {
  const w = Math.max(0, Math.min(1, frac)) * 100;
  return el("span", { class: "trace" + (kind ? " trace--" + kind : ""), "aria-hidden": "true" },
    el("span", { class: "trace__line" }, el("i", { style: "width:" + w + "%" })), via(kind === "top" ? "signal" : kind));
}

function toast(kind, title, body, role) {
  const text = el("div", { class: "ct-toast__text" }, el("p", { class: "ct-toast__t", text: title }),
    body ? el("p", { class: "ct-toast__b", text: body }) : null,
    kind === "fault" ? el("span", { class: "ct-cutline", "aria-hidden": "true" }, el("i"), el("i")) : null);
  return el("div", { class: "ct-frame ct-frame--ice ct-toast ct-toast--" + kind + " is-new", role: role || (kind === "fault" ? "alert" : "status") }, via(kind), text);
}
function notice(node) { $("#notice").replaceChildren(...(node ? [node] : [])); }
const showError = (title, body) => notice(title ? toast("fault", title, body) : null);

/* ---- Queue ---- */
function renderQueue() {
  $("#queue").replaceChildren(...files.map((f, i) =>
    el("li", {}, el("span", { class: "name", text: f.name, title: f.name }),
      el("button", { type: "button", class: "rm", "aria-label": "Usuń z kolejki: " + f.name, onclick: () => { files.splice(i, 1); renderQueue(); } },
        icon("M6,6 L18,18 M18,6 L6,18")))));
  $("#go").disabled = files.length === 0;
  $("#clear").hidden = files.length === 0;
}
function addFiles(list) {
  const skipped = [];
  for (const f of list) {
    if (!/\.pdf$/i.test(f.name)) { skipped.push(f.name); continue; }
    if (!files.some((x) => x.name === f.name && x.size === f.size)) files.push(f);
  }
  if (skipped.length) showError("Pominięto " + skipped.length + " " + plural(skipped.length, "plik", "pliki", "plików"), skipped.join(", ") + ": to nie są pliki PDF. Wybierz pliki z rozszerzeniem .pdf.");
  renderQueue();
}

const drop = $("#drop");
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => { notice(null); addFiles(e.dataTransfer.files); });
$("#file").addEventListener("change", (e) => { notice(null); addFiles(e.target.files); e.target.value = ""; });
$("#clear").addEventListener("click", () => { files = []; renderQueue(); $("#results").hidden = true; notice(null); });

/* ---- Process ---- */
const goFace = () => $("#go .ct-btn__face");
function setBusy(on) {
  const b = $("#go");
  b.toggleAttribute("aria-busy", on);
  if (on) b.setAttribute("aria-busy", "true");
  goFace().textContent = on ? "Przetwarzanie" : "Przetwórz sprawę";
  b.disabled = on || files.length === 0;
  $("#progress").hidden = !on;
}

$("#go").addEventListener("click", async () => {
  if ($("#go").disabled) return;
  notice(null); $("#results").hidden = true;
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f, f.name));
  fd.append("case", $("#case").value.trim() || "sprawa");
  setBusy(true);
  try {
    const r = await fetch("/api/process", { method: "POST", body: fd });
    if (!r.ok) {
      let m = "Serwer odrzucił zapytanie (" + r.status + "). Sprawdź pliki i spróbuj ponownie.";
      try { const j = await r.json(); if (typeof j.detail === "string") m = j.detail; } catch (_) {}
      throw new Error(m);
    }
    last = await r.json();
    render(last);
  } catch (e) {
    showError("Nie udało się przetworzyć plików", (e && e.message) || "Sprawdź, czy serwer działa, i spróbuj ponownie.");
  } finally {
    setBusy(false);
  }
});

function saveBlob(name, blob) {
  const a = el("a", { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); a.remove();
}

$("#zip").addEventListener("click", async () => {
  if (!last) return;
  const filesObj = {};
  last.documents.forEach((d) => {  // same tree as the CLI: a rejected document gets an empty JSON {}
    if (d.output_name && d.data) filesObj[d.output_name] = d.data;
    else if (d.input_name) filesObj[d.input_name.replace(/\.pdf$/i, "").replace(/[^\p{L}\p{N}_.\- ()]/gu, "_") + ".json"] = {};
  });
  const r = await fetch("/api/zip", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case: last.case, files: filesObj }) });
  if (!r.ok) { showError("Nie udało się zbudować archiwum ZIP", "Przetwórz sprawę jeszcze raz i ponów pobieranie."); return; }
  saveBlob(last.case + ".zip", await r.blob());
});

/* ---- Results ---- */
function render(res) {
  $("#case-title").textContent = "Sprawa: " + res.case;
  const total = res.documents.length;
  const acc = res.documents.filter((d) => d.output_name).length;
  const rej = total - acc;
  $("#summary").textContent = "Rozpoznane: " + acc + ". Odrzucone: " + rej + (rej ? " (pusty JSON {})." : ".");
  $("#zip").disabled = acc === 0;
  notice(toast("live", "Przetworzono sprawę", total + " " + plural(total, "plik", "pliki", "plików") + ", " + acc + " rozpoznane, " + rej + " odrzucone."));

  const ch = $("#checks"); ch.replaceChildren();
  if (res.checks.length) {
    ch.append(el("div", { class: "checks" }, el("h3", { class: "ct-h", text: "Spójność sprawy" }),
      el("ul", {}, res.checks.map((c) => el("li", {},
        c.ok === true ? tag("live", "Zgodne") : c.ok === false ? tag("fault", "Niezgodne") : tag("", "Nie dotyczy"),
        el("span", { text: c.name }),
        c.detail ? el("span", { class: "ct-cap detail", text: c.detail }) : null)))));
  }
  $("#docs").replaceChildren(...res.documents.map(docCard));
  $("#results").hidden = false;
  $("#results").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
}

function docCard(d, idx) {
  const c = d.classification;
  const rejected = !d.output_name;
  const label = rejected ? "Odrzucony" : (CLASS_PL[c.doc_class] || c.doc_class);

  const title = el("div", { class: "doc__title" },
    rejected ? tag("fault", "Odrzucony") : tag("live", "Rozpoznany"),
    el("h3", { class: "ct-panel-title", text: rejected ? "Brak pasującej klasy" : label }),
    el("p", { class: "doc__file" }, d.input_name, d.output_name ? "  →  " + d.output_name : ""));
  const score = el("div", { class: "doc__score" },
    el("span", { class: "ct-readout", text: fmtNum(c.score) }),
    el("span", { class: "ct-cap", text: "wynik klasyfikacji" }));

  const entries = Object.entries(c.scores || {}).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map((e) => e[1]));
  const scores = entries.length ? el("div", { class: "scores", role: "group", "aria-label": "Wyniki dla poszczególnych klas" },
    entries.map(([k, v], i) => el("div", { class: "srow" },
      el("span", { class: "k", text: CLASS_PL[k] || k }),
      trace(v / max, i === 0 && !rejected ? "top" : ""),
      el("span", { class: "n", text: fmtNum(v) })))) : null;

  const reason = el("div", { class: "doc__reason" },
    el("p", { class: "ct-label", text: rejected ? "Powód odrzucenia" : "Dlaczego ta klasa" }),
    el("p", { class: "ct-body", text: c.reason || (rejected ? "dokument nie pasuje do żadnej znanej klasy" : "brak opisu") }));
  const warns = d.warnings.length ? el("div", { class: "warns" }, d.warnings.map((w) => el("div", {}, via("fault"), el("span", { text: w })))) : null;

  const card = el("article", { class: "ct-frame ct-frame--ice ct-panel doc" + (rejected ? " doc--rejected" : "") },
    el("div", { class: "doc__head" }, title, score), reason, scores, warns);
  if (rejected) return card;

  const id = "d" + idx;
  const jsonText = pretty(d.data);
  const copyFace = el("span", { class: "ct-btn__face", text: "Kopiuj JSON" });
  const copyBtn = el("button", { type: "button", class: "ct-btn ct-btn--ground", onclick: async () => {
    try { await navigator.clipboard.writeText(jsonText); copyFace.textContent = "Skopiowano"; }
    catch (_) { copyFace.textContent = "Nie skopiowano. Zaznacz tekst i skopiuj ręcznie"; }
    setTimeout(() => (copyFace.textContent = "Kopiuj JSON"), 2400);
  } }, copyFace);
  const jsonPane = el("div", { class: "pane", id: id + "-json", role: "tabpanel", "aria-labelledby": id + "-t2", hidden: "" },
    el("div", { class: "tools" }, copyBtn,
      key("Pobierz JSON", { title: "Pobierz " + d.output_name, kind: "ground", icon: icon("M12,4 V16 M7,11 L12,16 L17,11 M4,15 V20 H20 V15"),
        onclick: () => saveBlob(d.output_name, new Blob([jsonText + "\n"], { type: "application/json" })) })),
    el("div", { class: "ct-frame ct-frame--well json-box" }, el("pre", { class: "json ct-bar", tabindex: "0", role: "region", "aria-label": "JSON pliku " + d.output_name, text: jsonText })));
  const evPane = el("div", { class: "pane", id: id + "-ev", role: "tabpanel", "aria-labelledby": id + "-t1" }, evidenceTable(d.evidence));

  const mk = (tid, t, pane, sel) => el("button", { type: "button", role: "tab", class: "tab", id: tid, "aria-selected": sel, "aria-controls": pane.id, tabindex: sel === "true" ? "0" : "-1" }, t, via("signal"));
  const t1 = mk(id + "-t1", "Dowody dla pól (" + d.evidence.length + ")", evPane, "true");
  const t2 = mk(id + "-t2", "JSON", jsonPane, "false");
  const choose = (t) => {
    [[t1, evPane], [t2, jsonPane]].forEach(([b, p]) => {
      const on = b === t;
      b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1; p.hidden = !on;
    });
  };
  [t1, t2].forEach((t) => {
    t.addEventListener("click", () => choose(t));
    t.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const o = t === t1 ? t2 : t1; choose(o); o.focus(); e.preventDefault();
    });
  });
  card.append(el("div", { class: "tabs", role: "tablist", "aria-label": "Widok dokumentu " + d.input_name }, t1, t2), evPane, jsonPane);
  return card;
}

function show(v) {
  if (v === null || v === undefined) return el("span", { class: "null", text: "null" });
  return typeof v === "string" ? v : JSON.stringify(v);
}
function snippetCell(snippet, value) {
  if (!snippet) return el("span", { class: "null", text: "brak" });
  const v = value == null ? "" : String(value);
  const i = v ? snippet.indexOf(v) : -1;
  if (i < 0) return snippet;
  return [snippet.slice(0, i), el("mark", { text: v }), snippet.slice(i + v.length)];
}
function evidenceTable(ev) {
  if (!ev.length) return el("p", { class: "ct-body empty", text: "Silnik nie zwrócił dowodów dla pól tego dokumentu. Pola pojawią się tutaj, gdy reguła dla tej klasy je wyciągnie." });
  const fid = "f" + Math.random().toString(36).slice(2, 8);
  const filter = el("input", { id: fid, type: "search", placeholder: "Pole, wartość lub reguła", autocomplete: "off" });
  const rows = ev.map((e) => {
    const cf = e.confidence == null ? 1 : e.confidence;
    const kind = cf >= 0.85 ? "live" : cf >= 0.6 ? "arc" : "fault";
    const tr = el("tr", {},
      el("td", { class: "path", text: e.path }),
      el("td", { class: "val" }, show(e.value)),
      el("td", { class: "ct-num", text: e.page == null ? "–" : String(e.page) }),
      el("td", { class: "snip" }, snippetCell(e.snippet, e.value)),
      el("td", { class: "rule", text: e.rule || "–" }),
      el("td", { class: "cf ct-num" }, trace(cf, kind), fmtNum(cf)));
    tr.dataset.q = (e.path + " " + (e.value == null ? "" : e.value) + " " + (e.rule || "")).toLowerCase();
    return tr;
  });
  const count = el("p", { class: "ct-cap", "aria-live": "polite", text: "Pokazano " + rows.length + " z " + rows.length });
  filter.addEventListener("input", () => {
    const q = filter.value.toLowerCase().trim(); let n = 0;
    rows.forEach((r) => { const h = !!q && !r.dataset.q.includes(q); r.hidden = h; if (!h) n++; });
    count.textContent = "Pokazano " + n + " z " + rows.length;
  });
  const head = el("tr", {}, [["Pole"], ["Wartość"], ["Strona", "ct-num"], ["Fragment źródła"], ["Reguła"], ["Pewność", "ct-num"]].map(([h, c]) => el("th", { scope: "col", class: c || "", text: h })));
  return el("div", { class: "pane" },
    el("div", { class: "ct-field ev-filter" }, el("label", { class: "ct-field__label", for: fid, text: "Filtruj dowody" }), el("span", { class: "ct-input" }, filter), count),
    el("div", { class: "ct-table-box ct-bar ev-box", tabindex: "0", role: "region", "aria-label": "Tabela dowodów dla pól" },
      el("table", { class: "ct-table ev" }, el("thead", {}, head), el("tbody", {}, rows))));
}
