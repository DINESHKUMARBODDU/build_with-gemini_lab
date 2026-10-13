(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const shell = $("#shell"), thread = $("#thread"), scroller = $("#scroll"), form = $("#composer");
  const input = $("#question"), sendBtn = $("#send"), counter = $("#counter"), welcome = $("#welcome");
  const history = [];
  let busy = false;

  // ---------- helpers ----------
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function svg(tag, attrs, text) {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (text != null) n.textContent = text;
    return n;
  }
  const nf = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
  const fmt = (v) => (typeof v === "number" ? nf.format(v) : v == null ? "–" : String(v));
  const trunc = (s, n) => (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s));
  const scrollDown = () => requestAnimationFrame(() => { scroller.scrollTop = scroller.scrollHeight; });
  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 2200);
  }
  function rich(parent, text) {
    String(text).split(/\n{2,}/).forEach((par) => {
      const p = el("p");
      par.split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
        if (/^\*\*[^*]+\*\*$/.test(part)) p.appendChild(el("strong", null, part.slice(2, -2)));
        else if (part) p.appendChild(document.createTextNode(part));
      });
      parent.appendChild(p);
    });
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast("Copied to clipboard"); }
    catch { toast("Copy failed. Select the text manually."); }
  }
  function downloadCsv(q) {
    const esc = (v) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const csv = [q.columns, ...q.rows].map((r) => r.map(esc).join(",")).join("\n");
    const a = el("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "datapilot-result.csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---------- charts ----------
  function chartSpec(q) {
    if (q.columns.length < 2 || q.rows.length < 2 || q.rows.length > 40) return null;
    const first = q.rows.map((r) => r[0]);
    if (first.some((v) => typeof v === "number")) return null;
    for (let c = 1; c < q.columns.length; c++) {
      if (q.rows.every((r) => r[c] == null || typeof r[c] === "number")) {
        const labels = first.map(String), values = q.rows.map((r) => Math.max(0, r[c] || 0));
        const time = labels.every((l) => /^\d{4}-\d{2}(-\d{2})?$/.test(l));
        return { labels, values, type: time ? "line" : "bar", name: q.columns[c] };
      }
    }
    return null;
  }
  function barChart(labels, values, name) {
    const rowH = 30, pad = 8, left = 170, right = 80, W = 680, H = pad * 2 + labels.length * rowH;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": `Bar chart of ${name}` });
    const max = Math.max(...values) || 1;
    labels.forEach((lab, i) => {
      const y = pad + i * rowH, w = Math.max(2, (values[i] / max) * (W - left - right));
      s.appendChild(svg("text", { x: left - 10, y: y + rowH / 2 + 4, "text-anchor": "end", class: "lbl" }, trunc(lab, 24)));
      const r = svg("rect", { x: left, y: y + 4, width: w, height: rowH - 10, rx: 5, class: "bar" });
      r.appendChild(svg("title", {}, `${lab}: ${fmt(values[i])}`));
      s.appendChild(r);
      s.appendChild(svg("text", { x: left + w + 8, y: y + rowH / 2 + 4, class: "val" }, compact.format(values[i])));
    });
    return s;
  }
  function lineChart(labels, values, name) {
    const W = 680, H = 280, l = 56, r = 20, t = 16, b = 44;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": `Line chart of ${name}` });
    const max = Math.max(...values) || 1;
    const x = (i) => l + (labels.length === 1 ? 0 : (i * (W - l - r)) / (labels.length - 1));
    const y = (v) => t + (1 - v / max) * (H - t - b);
    for (let k = 0; k <= 4; k++) {
      const v = (max * k) / 4, yy = y(v);
      s.appendChild(svg("line", { x1: l, x2: W - r, y1: yy, y2: yy, class: "grid" }));
      s.appendChild(svg("text", { x: l - 8, y: yy + 4, "text-anchor": "end", class: "lbl" }, compact.format(v)));
    }
    s.appendChild(svg("polyline", { points: values.map((v, i) => `${x(i)},${y(v)}`).join(" "), class: "line", fill: "none" }));
    values.forEach((v, i) => {
      const c = svg("circle", { cx: x(i), cy: y(v), r: 3.5, class: "dot" });
      c.appendChild(svg("title", {}, `${labels[i]}: ${fmt(v)}`));
      s.appendChild(c);
    });
    const step = Math.ceil(labels.length / 8);
    labels.forEach((lab, i) => { if (i % step === 0) s.appendChild(svg("text", { x: x(i), y: H - b + 22, "text-anchor": "middle", class: "lbl" }, lab)); });
    return s;
  }

  // ---------- result block ----------
  function resultBlock(q) {
    const wrap = el("div", "result");
    const head = el("div", "result-head");
    head.appendChild(el("span", "meta", `${q.row_count} row${q.row_count === 1 ? "" : "s"}${q.truncated ? " (first " + q.row_count + " shown)" : ""}`));

    const tableWrap = el("div", "table-wrap");
    const table = el("table"), thead = el("thead"), hr = el("tr");
    const numeric = q.columns.map((_, c) => q.rows.length > 0 && q.rows.every((r) => r[c] == null || typeof r[c] === "number"));
    q.columns.forEach((c, i) => hr.appendChild(el("th", numeric[i] ? "num" : "", c)));
    thead.appendChild(hr); table.appendChild(thead);
    const tbody = el("tbody");
    q.rows.forEach((r) => {
      const tr = el("tr");
      r.forEach((v, i) => tr.appendChild(el("td", numeric[i] ? "num" : "", fmt(v))));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody); tableWrap.appendChild(table);

    const spec = chartSpec(q);
    let chartWrap = null;
    if (spec) {
      chartWrap = el("div", "chart-wrap");
      chartWrap.appendChild(spec.type === "line" ? lineChart(spec.labels, spec.values, spec.name) : barChart(spec.labels, spec.values, spec.name));
      const tabs = el("div", "tabs"); tabs.setAttribute("role", "tablist");
      const tTable = el("button", "tab", "Table"), tChart = el("button", "tab", "Chart");
      [tTable, tChart].forEach((b) => { b.type = "button"; b.setAttribute("role", "tab"); tabs.appendChild(b); });
      const show = (chart) => {
        tChart.setAttribute("aria-selected", chart); tTable.setAttribute("aria-selected", !chart);
        chartWrap.hidden = !chart; tableWrap.hidden = chart;
      };
      tTable.onclick = () => show(false); tChart.onclick = () => show(true);
      head.appendChild(tabs);
      show(true); // charts first when available
    }
    const csv = el("button", "btn small", "CSV"); csv.type = "button"; csv.title = "Download as CSV";
    csv.onclick = () => downloadCsv(q);
    head.appendChild(csv);

    const details = el("details", "sql");
    details.appendChild(el("summary", null, "View SQL"));
    const body = el("div", "sql-body");
    const pre = el("pre"); pre.appendChild(el("code", null, q.sql));
    const actions = el("div", "sql-actions");
    const cp = el("button", "btn small", "Copy SQL"); cp.type = "button"; cp.onclick = () => copy(q.sql);
    actions.appendChild(cp); body.append(pre, actions); details.appendChild(body);

    wrap.append(head);
    if (chartWrap) wrap.appendChild(chartWrap);
    wrap.append(tableWrap, details);
    return wrap;
  }

  // ---------- messages ----------
  const avatarSvg = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17l5-6 4 3 7-9"/></svg>';
  function addUser(text) {
    const m = el("div", "msg user"); m.appendChild(el("div", "bubble", text));
    thread.appendChild(m); scrollDown();
  }
  function addPending() {
    const row = el("div", "msg assistant");
    const av = el("div", "avatar"); av.innerHTML = avatarSvg; av.setAttribute("aria-hidden", "true");
    const card = el("div", "card");
    const steps = ["Understanding your question", "Writing SQL", "Running the query", "Preparing your answer"];
    const list = el("ul", "steps");
    steps.forEach((s, i) => list.appendChild(el("li", i === 0 ? "active" : "", s)));
    card.appendChild(list); row.append(av, card); thread.appendChild(row); scrollDown();
    let i = 0;
    const timer = setInterval(() => {
      if (i < steps.length - 1) { list.children[i].className = "done"; i++; list.children[i].className = "active"; }
    }, 1100);
    return { card, stop: () => clearInterval(timer) };
  }
  function fillAnswer(card, data) {
    card.replaceChildren();
    rich(card, data.answer);
    (data.queries || []).forEach((q) => card.appendChild(resultBlock(q)));
    scrollDown();
  }
  function fillError(card, message, question) {
    card.replaceChildren(); card.classList.add("error");
    card.appendChild(el("p", "err-text", "Couldn't get an answer"));
    card.appendChild(el("p", "muted", message));
    const retry = el("button", "btn small", "Try again"); retry.type = "button"; retry.style.marginTop = "10px";
    retry.onclick = () => { input.value = question; autosize(); input.focus(); };
    card.appendChild(retry); scrollDown();
  }

  // ---------- ask ----------
  function setBusy(b) { busy = b; input.disabled = b; updateSend(); if (!b) input.focus(); }
  async function ask(question) {
    question = question.trim();
    if (busy || !question) return;
    if (question.length > 500) return toast("Please keep questions under 500 characters.");
    if (welcome) welcome.hidden = true;
    addUser(question);
    input.value = ""; autosize(); setBusy(true);
    const p = addPending();
    try {
      const res = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, history }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Request failed.");
      p.stop(); fillAnswer(p.card, data);
      history.push({ role: "user", text: question }, { role: "assistant", text: data.answer });
      while (history.length > 24) history.shift();
    } catch (err) {
      p.stop(); fillError(p.card, err.message || "Network error. Is the server running?", question);
    } finally { setBusy(false); }
  }

  // ---------- composer ----------
  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; updateSend(); }
  function updateSend() {
    sendBtn.disabled = busy || !input.value.trim();
    const n = input.value.length;
    counter.hidden = n < 400; counter.textContent = `${n}/500`;
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });

  // ---------- sidebar, theme, new chat ----------
  const closeSide = () => shell.classList.remove("open");
  $("#menu").onclick = () => shell.classList.add("open");
  $("#scrim").onclick = closeSide;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSide(); });
  $("#theme").onclick = () => {
    const root = document.documentElement;
    const cur = root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (_) {}
  };
  try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch (_) {}
  $("#new-chat").onclick = () => {
    history.length = 0;
    thread.querySelectorAll(".msg").forEach((n) => n.remove());
    welcome.hidden = false; closeSide(); input.focus();
  };

  // ---------- initial data ----------
  async function init() {
    try {
      const res = await fetch("/api/schema");
      const info = await res.json();
      const samples = $("#samples"), cards = $("#cards"), schema = $("#schema"), stats = $("#stats");
      info.samples.forEach((s) => {
        const b = el("button", "sample", s.q); b.type = "button";
        b.onclick = () => { closeSide(); ask(s.q); };
        samples.appendChild(b);
        const c = el("button", "qcard"); c.type = "button";
        c.append(el("strong", null, s.q), el("span", null, s.hint));
        c.onclick = () => ask(s.q);
        cards.appendChild(c);
      });
      schema.replaceChildren();
      info.tables.forEach((t) => {
        const d = el("details"), sum = el("summary", null, t.name);
        sum.appendChild(el("span", null, `${nf.format(t.rows)} rows`));
        const ul = el("ul");
        t.columns.forEach((c) => { const li = el("li", null, c.name); li.appendChild(el("i", null, c.type.toLowerCase())); ul.appendChild(li); });
        d.append(sum, ul); schema.appendChild(d);
        stats.appendChild(el("span", "chip", `${t.name}: ${nf.format(t.rows)}`));
      });
    } catch (_) {
      $("#schema").textContent = "Couldn't load the schema.";
    }
  }
  init();
  input.focus();
})();
