/* ── Download page controller ─────────────────────────── */

// Reuse the same base paths and SHIPS / BUOYS / THERMISTORS / ARCTSUM /
// SVALMIZ arrays already defined in csv-loader.js.

// ── Build the full instrument catalogue ───────────────────────────────────────

async function _buildCatalogue() {
  // IABP is dynamic — read the index first.
  let iabpItems = [];
  try {
    const resp = await fetch(`${IABP_BASE}/_index.json`);
    if (resp.ok) {
      const index = await resp.json();
      iabpItems = index.map((m) => ({
        type: "iabp",
        id: m.id,
        name: m.name || m.id,
        file: `${IABP_BASE}/${m.id}.csv`,
        tsField: "time",
      }));
    }
  } catch (_) {}

  return [
    {
      key: "ships",
      label: "Ships",
      tagClass: "ship-tag",
      tagText: "SHIP",
      items: SHIPS.map((s) => ({
        type: "ship",
        id: s.id,
        name: s.name,
        file: `${SHIPS_BASE}/${s.id}.csv`,
        tsField: s.tsField,
      })),
    },
    {
      key: "simba",
      label: "SIMBA Ice Buoys",
      tagClass: "simba-tag",
      tagText: "SIMBA",
      items: BUOYS.map((b) => ({
        type: "simba",
        id: b.id,
        name: b.name,
        file: `${SIMBA_BASE}/${b.deploymentId}.csv`,
        tsField: b.tsField,
      })),
    },
    {
      key: "thermistor",
      label: "Thermistor Chain Buoys",
      tagClass: "thermistor-tag",
      tagText: "BUOY",
      items: THERMISTORS.map((t) => ({
        type: "thermistor",
        id: t.id,
        name: t.name,
        file: `${THERMISTOR_BASE}/${t.id}_ts.csv`,
        tsField: t.tsField,
      })),
    },
    {
      key: "arctsum",
      label: "ArctSum 2025 Buoys",
      tagClass: "arctsum-tag",
      tagText: "ArctSum",
      items: ARCTSUM.map((b) => ({
        type: "arctsum",
        id: b.id,
        name: b.name,
        file: `${ARCTSUM_BASE}/${b.id}_ts.csv`,
        tsField: b.tsField,
      })),
    },
    {
      key: "svalmiz",
      label: "SvalMIZ 2026 Buoys",
      tagClass: "svalmiz-tag",
      tagText: "SvalMIZ",
      items: SVALMIZ.map((b) => ({
        type: "svalmiz",
        id: b.id,
        name: b.name,
        file: `${SVALMIZ_BASE}/${b.id}_ts.csv`,
        tsField: b.tsField,
      })),
    },
    {
      key: "iabp",
      label: "IABP Arctic Buoys",
      tagClass: "iabp-tag",
      tagText: "IABP",
      items: iabpItems,
    },
  ];
}

// ── Date helpers ──────────────────────────────────────────────────────────────

function _toDateStr(d) {
  return d.toISOString().slice(0, 10);
}

function _dateFromInput(id) {
  const v = document.getElementById(id).value;
  return v ? new Date(v + "T00:00:00Z") : null;
}

// ── Filter a CSV text to a date range, keeping the header ────────────────────

function _filterCSV(text, tsField, from, to) {
  if (!text.trim()) return text;
  const lines = text.split("\n");
  const header = lines[0];
  const headers = header.split(",").map((h) => h.trim());
  const tsIdx = headers.indexOf(tsField);

  if (tsIdx === -1 || (!from && !to)) return text;

  const fromStr = from ? from.toISOString().slice(0, 10) : "";
  const toStr   = to   ? to.toISOString().slice(0, 23)   : "";

  const kept = lines.slice(1).filter((line) => {
    if (!line.trim()) return false;
    const ts = (line.split(",")[tsIdx] || "").trim();
    if (!ts) return true;               // keep if unparseable
    if (fromStr && ts < fromStr) return false;
    if (toStr   && ts > toStr)  return false;
    return true;
  });

  return [header, ...kept].join("\n");
}

// ── Selected instruments map: id → {item, group} ─────────────────────────────

const _selected = new Map();

function _updateSummary() {
  const summaryEl = document.getElementById("dl-summary");
  const btnEl     = document.getElementById("dl-btn");
  const n = _selected.size;
  if (n === 0) {
    summaryEl.textContent = "No instruments selected.";
    btnEl.disabled = true;
  } else {
    const label = n === 1 ? "1 instrument" : `${n} instruments`;
    summaryEl.textContent = `${label} selected — will produce ${n === 1 ? "one CSV file" : "a ZIP archive with " + n + " CSV files"}.`;
    btnEl.disabled = false;
    document.getElementById("dl-btn-label").textContent =
      n === 1 ? "Download CSV" : "Download ZIP";
  }
}

// ── Build the instrument-group UI ─────────────────────────────────────────────

function _buildGroupsUI(catalogue) {
  const container = document.getElementById("instrument-groups");
  container.innerHTML = "";

  catalogue.forEach((group) => {
    if (!group.items.length) return;

    const groupDiv = document.createElement("div");
    groupDiv.className = "dl-group";

    // Header row
    const header = document.createElement("div");
    header.className = "dl-group-header";

    const groupCb = document.createElement("input");
    groupCb.type = "checkbox";
    groupCb.id   = `group-${group.key}`;

    const labelEl = document.createElement("label");
    labelEl.htmlFor = `group-${group.key}`;
    labelEl.className = "dl-group-label";
    labelEl.textContent = group.label;

    const count = document.createElement("span");
    count.className = "dl-group-count";
    count.textContent = `${group.items.length} instruments`;

    const expandBtn = document.createElement("button");
    expandBtn.className = "dl-expand-btn";
    expandBtn.setAttribute("aria-label", "Toggle details");
    expandBtn.textContent = "▼";

    header.appendChild(groupCb);
    header.appendChild(labelEl);
    header.appendChild(count);
    header.appendChild(expandBtn);
    groupDiv.appendChild(header);

    // Instruments list
    const instrDiv = document.createElement("div");
    instrDiv.className = "dl-instruments collapsed";

    group.items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "dl-instr-item";

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.id   = `instr-${item.id}`;
      cb.dataset.id = item.id;

      const lbl = document.createElement("label");
      lbl.htmlFor = `instr-${item.id}`;

      const tag = document.createElement("span");
      tag.className = `dl-instr-tag obs-tag ${group.tagClass}`;
      tag.textContent = group.tagText;

      lbl.appendChild(tag);
      lbl.appendChild(document.createTextNode(" " + item.name));

      row.appendChild(cb);
      row.appendChild(lbl);
      instrDiv.appendChild(row);

      cb.addEventListener("change", () => {
        if (cb.checked) {
          _selected.set(item.id, item);
        } else {
          _selected.delete(item.id);
        }
        // Update group checkbox state
        const all  = [...instrDiv.querySelectorAll("input[type=checkbox]")];
        const nChk = all.filter((c) => c.checked).length;
        groupCb.indeterminate = nChk > 0 && nChk < all.length;
        groupCb.checked = nChk === all.length;
        _updateSummary();
      });
    });

    groupDiv.appendChild(instrDiv);

    // Group checkbox: toggle all children
    groupCb.addEventListener("change", () => {
      instrDiv.querySelectorAll("input[type=checkbox]").forEach((cb) => {
        cb.checked = groupCb.checked;
        const id = cb.dataset.id;
        const item = group.items.find((i) => i.id === id);
        if (item) {
          if (groupCb.checked) _selected.set(id, item);
          else                 _selected.delete(id);
        }
      });
      _updateSummary();
    });

    // Expand / collapse toggle — clicking the header row (anywhere) toggles
    function _toggle() {
      const open = !instrDiv.classList.contains("collapsed");
      instrDiv.classList.toggle("collapsed", open);
      expandBtn.classList.toggle("open", !open);
    }
    expandBtn.addEventListener("click", (e) => { e.stopPropagation(); _toggle(); });
    labelEl.addEventListener("click", (e) => { e.preventDefault(); _toggle(); });
    count.addEventListener("click", _toggle);
    header.addEventListener("click", (e) => {
      if (e.target !== groupCb && e.target !== labelEl) _toggle();
    });

    container.appendChild(groupDiv);
  });
}

// ── Download handler ──────────────────────────────────────────────────────────

async function _doDownload(catalogue) {
  if (_selected.size === 0) return;

  const from = _dateFromInput("date-from");
  const to   = _dateFromInput("date-to");
  // Make 'to' inclusive — end of the selected day UTC
  const toInclusive = to ? new Date(to.getTime() + 86399999) : null;

  const progressEl = document.getElementById("dl-progress");
  const btnEl      = document.getElementById("dl-btn");
  btnEl.disabled   = true;
  progressEl.style.display = "";
  progressEl.innerHTML = `
    <span id="dl-status-text">Preparing…</span>
    <div class="dl-progress-bar"><div class="dl-progress-bar-fill" id="dl-bar" style="width:0%"></div></div>
  `;

  const items  = [..._selected.values()];
  const total  = items.length;
  let done     = 0;

  function _setProgress(n, msg) {
    const pct = Math.round((n / total) * 100);
    const bar = document.getElementById("dl-bar");
    const txt = document.getElementById("dl-status-text");
    if (bar) bar.style.width = pct + "%";
    if (txt) txt.textContent = msg;
  }

  try {
    if (total === 1) {
      // Single file — direct download
      const item = items[0];
      _setProgress(0, `Fetching ${item.name}…`);
      const resp = await fetch(item.file);
      if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${item.name}`);
      const text = _filterCSV(await resp.text(), item.tsField, from, toInclusive);
      _setProgress(1, "Done");
      _triggerDownload(text, `${item.id}.csv`, "text/csv");
    } else {
      // Multiple files → ZIP
      const zip = new JSZip();
      for (const item of items) {
        _setProgress(done, `Fetching ${item.name} (${done + 1}/${total})…`);
        try {
          const resp = await fetch(item.file);
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          const text = _filterCSV(await resp.text(), item.tsField, from, toInclusive);
          zip.file(`${item.type}/${item.id}.csv`, text);
        } catch (e) {
          console.warn(`Skipped ${item.name}: ${e.message}`);
        }
        done++;
      }
      _setProgress(total, "Building ZIP…");
      const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE" });
      const fromStr = from ? from.toISOString().slice(0, 10) : "all";
      const toStr   = to   ? to.toISOString().slice(0, 10)   : "all";
      _triggerDownloadBlob(blob, `arctic_obs_${fromStr}_${toStr}.zip`);
      _setProgress(total, `Done — ${total} files in ZIP.`);
    }
  } catch (err) {
    document.getElementById("dl-status-text").textContent = "Error: " + err.message;
  } finally {
    btnEl.disabled = false;
  }
}

function _triggerDownload(text, filename, mime) {
  const blob = new Blob([text], { type: mime });
  _triggerDownloadBlob(blob, filename);
}

function _triggerDownloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement("a");
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// ── Init ──────────────────────────────────────────────────────────────────────

(async function init() {
  // Default dates: last 30 days
  const today = new Date();
  const ago30 = new Date(today);
  ago30.setDate(ago30.getDate() - 30);
  document.getElementById("date-to").value   = _toDateStr(today);
  document.getElementById("date-from").value = _toDateStr(ago30);

  // Preset buttons
  document.querySelectorAll(".preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".preset-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const days = parseInt(btn.dataset.days, 10);
      const now  = new Date();
      document.getElementById("date-to").value = _toDateStr(now);
      if (days === 0) {
        document.getElementById("date-from").value = "";
      } else {
        const from = new Date(now);
        from.setDate(from.getDate() - days);
        document.getElementById("date-from").value = _toDateStr(from);
      }
    });
  });
  // Mark 30-day preset active by default
  document.querySelector('.preset-btn[data-days="30"]').classList.add("active");

  // Build catalogue and UI
  const catalogue = await _buildCatalogue();
  _buildGroupsUI(catalogue);

  // Download button
  document.getElementById("dl-btn").addEventListener("click", () => _doDownload(catalogue));
})();
