// In-browser company search over companies.json, ranked as opencorpfilings.directory ranks it.
(function () {
  "use strict";
  const LEGAL = new Set(["inc", "incorporated", "corp", "corporation", "co", "company", "plc", "ltd", "limited", "llc",
    "lp", "sa", "se", "ag", "nv", "bv", "spa", "oyj", "abp", "ab", "asa", "as", "a/s", "kk", "sas", "sca", "the"]);
  const TIER = { supported: 0, limited: 1, experimental: 2 };
  const REGIONS = typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames(["en"], { type: "region" }) : null;
  function market(code) {
    try { return (REGIONS && REGIONS.of(code === "UK" ? "GB" : code)) || code; } catch (error) { return code; }
  }
  const LIMIT = 20;

  const query = document.getElementById("ocf-find-query");
  const status = document.getElementById("ocf-find-status");
  const results = document.getElementById("ocf-find-results");
  const uk = document.getElementById("ocf-find-uk");
  const sources = document.getElementById("ocf-find-sources");
  let rows = [];

  function normal(text) {
    return (text || "").normalize("NFKC").normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase()
      .replace(/[^\p{L}\p{N}_/]+/gu, " ").trim().replace(/\s+/g, " ");
  }
  function tokens(text) {
    return normal(text).split(" ").filter((token) => token && !LEGAL.has(token));
  }
  function score(row, raw, normalQuery, queryTokens) {
    if (row.exact.has(raw)) return 100;
    let best = 0;
    for (const name of row.names) {
      const t = name.tokens;
      if (t.length && t.length === queryTokens.length && t.every((token, i) => token === queryTokens[i])) best = Math.max(best, 90);
      else if (queryTokens.length && queryTokens.every((token, i) => t[i] === token)) best = Math.max(best, 70);
      else if (queryTokens.length && queryTokens.every((token) => t.includes(token))) best = Math.max(best, 50);
      else if (raw && name.normal.includes(normalQuery)) best = Math.max(best, 30);
    }
    return best;
  }
  function escape(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }
  function call(row) {
    const source = row.source ? `, source="${row.source}"` : "";
    return `Company("${row.identifier}", market="${row.market}"${source})`;
  }

  function render() {
    const raw = query.value.trim().toLowerCase();
    results.innerHTML = "";
    uk.hidden = !raw;
    if (raw) {
      const link = "https://find-and-update.company-information.service.gov.uk/search/companies?q=" + encodeURIComponent(query.value.trim());
      uk.innerHTML = `Looking for a UK company? <a href="${link}" target="_blank" rel="noopener">Search Companies House</a>, then use its company number: <code>Company("00502851", market="UK")</code>.`;
    }
    if (!raw) { status.textContent = `${rows.length.toLocaleString()} companies. Type to search.`; return; }
    const normalQuery = normal(query.value), queryTokens = tokens(query.value);
    const scored = [];
    for (const row of rows) {
      const s = score(row, raw, normalQuery, queryTokens);
      if (s) scored.push([-s, TIER[row.tier] ?? 3, row.name.length, row]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
    status.textContent = scored.length ? `${scored.length.toLocaleString()} match${scored.length === 1 ? "" : "es"}` +
      (scored.length > LIMIT ? `, showing the best ${LIMIT}` : "") : "No match in these lists.";
    for (const [, , , row] of scored.slice(0, LIMIT)) {
      const item = document.createElement("li");
      const extra = [...row.tickers.filter((t) => t !== row.identifier), ...row.isins.slice(0, 2), row.lei !== row.identifier ? row.lei : null]
        .filter(Boolean).slice(0, 4).map(escape).join(" · ");
      item.innerHTML =
        `<div class="ocf-find-head"><strong>${escape(row.name)}</strong>` +
        `<span class="ocf-find-market">${escape(market(row.market))}${row.source === "esef_index" ? " · ESEF index" : ""}</span>` +
        `<span class="ocf-find-tier ocf-find-tier--${escape(row.tier)}">${escape(row.tier)}</span></div>` +
        (extra ? `<div class="ocf-find-ids">${extra}</div>` : "") +
        `<div class="ocf-find-call"><code>${escape(call(row))}</code><button type="button" class="ocf-find-copy">Copy</button></div>`;
      item.querySelector("button").addEventListener("click", (event) => {
        navigator.clipboard.writeText(call(row)).then(() => { event.target.textContent = "Copied"; });
      });
      results.appendChild(item);
    }
  }

  function load(url) { return fetch(url).then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }); }
  load("companies.json").then((data) => Promise.all([
    data, ...(data.related_datasets || []).map(load)
  ])).then((datasets) => {
    const data = datasets[0];
    const at = Object.fromEntries(data.fields.map((field, i) => [field, i]));
    rows = datasets.flatMap((dataset) => dataset.rows).map((values) => {
      const row = Object.fromEntries(data.fields.map((field) => [field, values[at[field]]]));
      row.exact = new Set([row.identifier, ...row.tickers, ...row.isins, row.lei || "", ...row.aliases]
        .filter(Boolean).map((value) => value.toLowerCase()));
      row.names = [row.name, ...row.aliases].map((name) => ({ normal: normal(name), tokens: tokens(name) }));
      return row;
    });
    sources.innerHTML = `Lists built ${escape(data.built_at.slice(0, 10))} from: ` + datasets.flatMap((dataset) => dataset.sources).map((source) =>
      `<a href="${escape(source.url)}" target="_blank" rel="noopener">${escape(source.name)}</a>` +
      (source.license_url ? ` (<a href="${escape(source.license_url)}">ODbL 1.0</a>)` : "")).join("; ") + ".";
    query.addEventListener("input", render);
    render();
    query.focus();
  }).catch((error) => {
    status.textContent = `The company list could not be loaded (${error.message}).`;
  });
})();
