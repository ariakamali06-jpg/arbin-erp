/* ==========================================================================
   Arbin Financial Suite — SPA controller (آربین)
   ========================================================================== */
"use strict";

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const state = {
  tenant: "default_company",
  fy: "fy_1405",
  view: "dashboard",
  openTabs: ["dashboard"],
  drilldown: {
    level: "group",
    groupCode: null,
    groupTitle: null,
    generalCode: null,
    generalTitle: null,
    subsidiaryCode: null,
    subsidiaryTitle: null,
  },
  accounts: [],          // flattened subsidiary accounts
  tree: [],
  products: [],
  warehouses: [],
  customers: [],
  payees: [],
  bankAccounts: [],
  suppliers: [],
  employees: [],
  lastRun: null,
  lastInvoice: null,
};

const TAB_LABELS = {
  dashboard: "📊 داشبورد",
  ledger: "📝 سند حسابداری",
  drilldown: "🔍 مرور حساب‌ها",
  docflow: "🔗 ارتباط اسناد",
  treasury: "💰 خزانه‌داری",
  inventory: "📦 انبار و کاردکس",
  sales: "🧾 فروش و فاکتور",
  payroll: "👥 حقوق و دستمزد",
  fixedAssets: "🏷️ اموال و دارایی",
  manufacturing: "🧪 فرمول ساخت",
  contracting: "📜 پیمانکاری",
  modules: "🧩 ماژول‌ها",
};

/* ---------------- helpers ---------------- */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const toFa = (s) => String(s).replace(/\d/g, (d) => FA_DIGITS[d]);
const money = (n) =>
  toFa(Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 }));
const todayISO = () => new Date().toISOString().slice(0, 10);
const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );

function toast(msg, type = "ok") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show " + type;
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = "toast"), 3200);
}

/* ---------------- loader & modal ---------------- */
let inflight = 0;
function loaderOn() {
  if (++inflight === 1) $("#loader").classList.add("open");
}
function loaderOff() {
  if (--inflight <= 0) {
    inflight = 0;
    $("#loader").classList.remove("open");
  }
}

function openModal(title, html) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = html;
  $("#modalOverlay").classList.add("open");
}

function closeModal() {
  $("#modalOverlay").classList.remove("open");
}

async function api(path, opts = {}) {
  const init = { headers: { "Content-Type": "application/json" }, ...opts };
  if (opts.body) init.body = JSON.stringify(opts.body);
  loaderOn();
  let res;
  try {
    res = await fetch("/api/v1" + path, init);
  } finally {
    loaderOff();
  }
  let data = {};
  try { data = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : "خطای " + res.status);
  }
  return data;
}

const STATUS_LABEL = {
  draft: ["پیش‌نویس", "gray"],
  approved: ["تایید شده", "info"],
  permanent: ["قید شده", "ok"],
  confirmed: ["تایید شده", "ok"],
  opening_entry: ["افتتاحیه", "warn"],
  closing_entry: ["اختتامیه", "warn"],
  cancelled: ["ابطال شده", "bad"],
  deleted: ["حذف شده", "gray"],
};

const CHEQUE_LABEL = {
  in_safe: ["نزد صندوق", "info"],
  deposited_to_bank: ["در جریان وصول", "warn"],
  cleared: ["وصول شده", "ok"],
  bounced: ["برگشتی", "bad"],
  transferred: ["واگذار شده", "gray"],
  returned: ["مسترد شده", "gray"],
  issued: ["صادره", "info"],
  cancelled: ["ابطال شده", "gray"],
};

const badge = (code, map) => {
  const [label, cls] = map[code] || [code, "gray"];
  return `<span class="badge ${cls}">${label}</span>`;
};

function fillSelect(sel, items, valueKey, labelKey, placeholder) {
  const el = typeof sel === "string" ? $(sel) : sel;
  if (!el) return;
  el.innerHTML =
    (placeholder ? `<option value="">${placeholder}</option>` : "") +
    items
      .map((i) => `<option value="${esc(i[valueKey])}">${esc(i[labelKey])}</option>`)
      .join("");
}

function flatTree(nodes, out = []) {
  nodes.forEach((n) => {
    if (n.level === "subsidiary") out.push({ code: n.code, title: n.title });
    if (n.children && n.children.length) flatTree(n.children, out);
  });
  return out;
}

/* ---------------- router ---------------- */
const TITLES = {
  dashboard: "داشبورد مدیریتی و شاخص‌های سلامت مالی",
  ledger: "سیستم حسابداری مالی (ثبت سند و دفاتر)",
  drilldown: "مرور جامع و چندسطحی حساب‌ها",
  docflow: "سیستم ارتباط اسناد و پیگیری زنجیره فرآیندها",
  treasury: "سیستم دریافت و پرداخت، خزانه‌داری و چک صیادی",
  inventory: "سیستم تأمین و انبارداری، کاردکس کالا",
  sales: "سیستم مشتریان، فروش و سامانه مؤدیان",
  payroll: "سیستم حقوق و دستمزد و پرسنلی",
  fixedAssets: "سیستم اموال، دارایی ثابت و استهلاک ماده ۱۴۹",
  manufacturing: "سیستم تولید، فرمول ساخت BOM و بهای تمام‌شده صنعتی",
  contracting: "سیستم پیمانکاری، قراردادها و صورت‌وضعیت‌ها",
  modules: "مدیریت بسته‌های صنفی و ماژول‌های فعال",
};

function go(view) {
  state.view = view;
  if (!state.openTabs.includes(view)) {
    state.openTabs.push(view);
  }
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  $("#viewTitle").textContent = TITLES[view] || "";
  renderTabs();
  refresh();
}

function renderTabs() {
  const strip = $("#tabStrip");
  if (!strip) return;
  strip.innerHTML = state.openTabs
    .map(
      (v) => `
    <div class="mdi-tab ${v === state.view ? "active" : ""}" data-tab="${v}">
      <span>${TAB_LABELS[v] || TITLES[v] || v}</span>
      ${v !== "dashboard" ? `<span class="tab-close" data-close-tab="${v}">×</span>` : ""}
    </div>`
    )
    .join("");

  $$("#tabStrip [data-tab]").forEach((tab) => {
    tab.onclick = (e) => {
      if (e.target.dataset.closeTab) return;
      go(tab.dataset.tab);
    };
  });
  $$("#tabStrip [data-close-tab]").forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      closeTab(btn.dataset.closeTab);
    };
  });
}

function closeTab(view) {
  if (view === "dashboard") return;
  state.openTabs = state.openTabs.filter((v) => v !== view);
  if (state.view === view) {
    const next = state.openTabs[state.openTabs.length - 1] || "dashboard";
    go(next);
  } else {
    renderTabs();
  }
}

/* ---------------- loaders ---------------- */
async function refresh() {
  try {
    if (state.view === "dashboard") await loadDashboard();
    else if (state.view === "ledger") await loadLedger();
    else if (state.view === "drilldown") await loadDrillDown();
    else if (state.view === "docflow") await loadDocumentFlow();
    else if (state.view === "treasury") await loadTreasury();
    else if (state.view === "inventory") await loadInventory();
    else if (state.view === "sales") await loadSales();
    else if (state.view === "payroll") await loadPayroll();
    else if (state.view === "fixedAssets") await loadFixedAssets();
    else if (state.view === "manufacturing") await loadManufacturing();
    else if (state.view === "contracting") await loadContracting();
    else if (state.view === "modules") await loadModulesView();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function loadShared() {
  await loadModules();
  state.tree = await api(`/tenants/${state.tenant}/accounts/tree`);
  state.accounts = flatTree(state.tree);
  const subs = await api(`/tenants/${state.tenant}/sub-ledgers`);
  state.subLedgers = subs || [];
  state.customers = subs.filter((s) => s.sub_ledger_type === "customer");
  state.suppliers = subs.filter((s) => s.sub_ledger_type === "supplier");
  state.bankAccounts = subs.filter((s) => s.sub_ledger_type === "bank");
  state.payees = subs.filter((s) => ["customer", "supplier"].includes(s.sub_ledger_type));
}

/* ---------------- 1. Dashboard ---------------- */
async function loadDashboard() {
  const d = await api(`/tenants/${state.tenant}/dashboard-summary?fiscal_year_id=${state.fy}`);
  const margin = d.total_sales ? (100 * d.net_profit) / d.total_sales : 0;
  const kpis = [
    ["موجودی بانک و صندوق", d.cash_and_bank, ""],
    ["مطالبات تجاری", d.total_receivables, "alt"],
    ["درآمد دوره", d.total_sales, "blue"],
    [
      "سود خالص دوره",
      d.net_profit,
      d.net_profit < 0 ? "red" : "",
      `حاشیه سود خالص: ${toFa(margin.toFixed(1))}٪`,
    ],
    ["کل دارایی‌ها", d.total_assets, ""],
    ["کل بدهی‌ها", d.total_liabilities, "red"],
  ];
  $("#kpis").innerHTML = kpis
    .map(
      ([label, val, cls, sub]) => `
      <div class="card kpi ${cls}">
        <div class="label">${label}</div>
        <div class="value">${money(val)} <span class="unit">تومان</span></div>
        ${sub ? `<div class="label" style="margin-top:4px;">${sub}</div>` : ""}
      </div>`
    )
    .join("");

  $("#recentEntries").innerHTML =
    (d.recent_entries || [])
      .map(
        (e) => `<tr>
          <td>${toFa(e.number)}</td>
          <td>${toFa(e.date_jalali || e.date)}</td>
          <td>${esc(e.description)}</td>
          <td>${badge(e.raw_status, STATUS_LABEL)}</td>
          <td class="num">${money(e.amount)}</td>
        </tr>`
      )
      .join("") || `<tr><td colspan="5" class="empty">سندی ثبت نشده است.</td></tr>`;

  $("#dashCustomers").innerHTML =
    (d.customers || [])
      .map(
        (c) => `<tr><td>${toFa(c.code)}</td><td>${esc(c.title)}</td><td>${toFa(c.phone || "—")}</td></tr>`
      )
      .join("") || `<tr><td colspan="3" class="empty">مشتری‌ای ثبت نشده است.</td></tr>`;

  $("#dashTotals").innerHTML = `
    <div class="t"><span>کل دارایی</span><strong>${money(d.total_assets)}</strong></div>
    <div class="t"><span>کل بدهی</span><strong>${money(d.total_liabilities)}</strong></div>
    <div class="t"><span>فاکتورها</span><strong>${toFa(d.total_invoiced || 0)}</strong></div>
    <div class="t"><span>سود خالص</span><strong>${money(d.net_profit)}</strong></div>`;
}

/* ---------------- 2. Ledger ---------------- */
function formatNumberWithCommas(str) {
  const clean = String(str).replace(/[^\d]/g, "");
  if (!clean) return "0";
  return Number(clean).toLocaleString("en-US");
}

function parseFormattedNumber(str) {
  return Number(String(str).replace(/[^\d]/g, "") || 0);
}

function reindexJeRows() {
  $$("#jeRows tbody tr").forEach((tr, idx) => {
    const cell = tr.querySelector(".row-idx");
    if (cell) cell.textContent = toFa(idx + 1);
  });
}

/* ================= Desktop Fast Lookup Dialog (F3) ================= */
let lookupState = {
  active: false,
  mode: "account", // "account" or "detail"
  onSelect: null,
  items: [],
  filtered: [],
  selectedIndex: 0,
  returnFocusEl: null,
};

function openLookup(mode, onSelect, initialQuery = "", returnEl = null) {
  lookupState.active = true;
  lookupState.mode = mode;
  lookupState.onSelect = onSelect;
  lookupState.returnFocusEl = returnEl || document.activeElement;
  lookupState.selectedIndex = 0;

  const overlay = $("#lookupOverlay");
  const title = $("#lookupTitle");
  const inp = $("#lookupInput");

  if (!overlay || !inp) return;

  if (mode === "account") {
    if (title) title.textContent = "جستجوی حساب معین (F3)";
    inp.placeholder = "کد یا عنوان حساب معین را وارد کنید…";
    lookupState.items = (state.accounts || []).map((a) => ({
      code: a.code,
      title: a.title,
      type: a.nature === "debtor" ? "بدهکار" : a.nature === "creditor" ? "بستانکار" : "معین",
      raw: a,
    }));
  } else {
    if (title) title.textContent = "جستجوی تفصیلی شناور (F3)";
    inp.placeholder = "کد، نام مشتری، تأمین‌کننده یا بانک را وارد کنید…";
    const allSubs = state.subLedgers && state.subLedgers.length ? state.subLedgers : [
      ...(state.bankAccounts || []),
      ...(state.customers || []),
      ...(state.suppliers || []),
    ];
    lookupState.items = allSubs.map((s) => ({
      code: s.code,
      title: s.title,
      type: s.sub_ledger_type === "bank" ? "بانک" : s.sub_ledger_type === "customer" ? "مشتری" : s.sub_ledger_type === "supplier" ? "تأمین‌کننده" : "تفصیلی",
      raw: s,
    }));
  }

  overlay.style.display = "flex";
  inp.value = initialQuery || "";
  filterLookup(inp.value);
  inp.focus();
  inp.select();
}

function closeLookup() {
  const overlay = $("#lookupOverlay");
  if (overlay) overlay.style.display = "none";
  lookupState.active = false;
  if (lookupState.returnFocusEl && typeof lookupState.returnFocusEl.focus === "function") {
    lookupState.returnFocusEl.focus();
  }
}

function filterLookup(q) {
  const query = (q || "").trim().toLowerCase();
  if (!query) {
    lookupState.filtered = lookupState.items.slice(0, 50);
  } else {
    lookupState.filtered = lookupState.items
      .filter((it) => String(it.code).toLowerCase().includes(query) || String(it.title).toLowerCase().includes(query))
      .slice(0, 50);
  }
  lookupState.selectedIndex = 0;
  renderLookup();
}

function renderLookup() {
  const body = $("#lookupBody");
  const count = $("#lookupCount");
  if (!body) return;
  if (count) count.textContent = `${toFa(lookupState.filtered.length)} مورد`;
  if (lookupState.filtered.length === 0) {
    body.innerHTML = `<tr><td colspan="4" class="empty" style="text-align:center; padding:20px; color:#94a3b8;">موردی یافت نشد.</td></tr>`;
    return;
  }
  body.innerHTML = lookupState.filtered
    .map(
      (it, idx) => `
      <tr class="${idx === lookupState.selectedIndex ? "active-row" : ""}" data-idx="${idx}">
        <td><strong style="color:#d97706;">${toFa(it.code)}</strong></td>
        <td>${esc(it.title)}</td>
        <td><span class="badge ${it.type === 'بانک' ? 'ok' : 'alt'}">${it.type}</span></td>
        <td><button type="button" class="btn sm" style="padding:2px 8px; font-size:11px;">انتخاب</button></td>
      </tr>`
    )
    .join("");

  $$("#lookupBody tr").forEach((tr) => {
    tr.onclick = () => {
      const idx = parseInt(tr.dataset.idx, 10);
      selectLookupItem(idx);
    };
  });

  scrollLookupActiveIntoView();
}

function scrollLookupActiveIntoView() {
  const activeTr = $(`#lookupBody tr.active-row`);
  if (activeTr) {
    activeTr.scrollIntoView({ block: "nearest" });
  }
}

function selectLookupItem(idx) {
  const item = lookupState.filtered[idx];
  if (item && lookupState.onSelect) {
    lookupState.onSelect(item);
  }
  closeLookup();
}

function initLookupEvents() {
  const inp = $("#lookupInput");
  const closeBtn = $("#lookupClose");
  const overlay = $("#lookupOverlay");

  if (closeBtn) closeBtn.onclick = closeLookup;
  if (overlay) {
    overlay.onclick = (e) => {
      if (e.target === overlay) closeLookup();
    };
  }

  if (inp) {
    inp.oninput = () => filterLookup(inp.value);
    inp.onkeydown = (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (lookupState.filtered.length > 0) {
          lookupState.selectedIndex = (lookupState.selectedIndex + 1) % lookupState.filtered.length;
          renderLookup();
        }
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (lookupState.filtered.length > 0) {
          lookupState.selectedIndex =
            (lookupState.selectedIndex - 1 + lookupState.filtered.length) % lookupState.filtered.length;
          renderLookup();
        }
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (lookupState.filtered.length > 0) {
          selectLookupItem(lookupState.selectedIndex);
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        closeLookup();
      }
    };
  }
}

function applyAutoBalance(targetInput, rowTr) {
  let dr = 0, cr = 0;
  $$("#jeRows tbody tr").forEach((r) => {
    if (r !== rowTr) {
      dr += parseFormattedNumber(r.querySelector(".jeDr").value || 0);
      cr += parseFormattedNumber(r.querySelector(".jeCr").value || 0);
    }
  });
  const drInp = rowTr.querySelector(".jeDr");
  const crInp = rowTr.querySelector(".jeCr");

  if (targetInput === crInp) {
    const curDr = parseFormattedNumber(drInp.value || 0);
    const needed = Math.max(0, (dr + curDr) - cr);
    crInp.value = formatNumberWithCommas(needed);
    toast(`بستانکار تراز شد: ${money(needed)} تومان`, "ok");
  } else {
    const curCr = parseFormattedNumber(crInp.value || 0);
    const needed = Math.max(0, (cr + curCr) - dr);
    drInp.value = formatNumberWithCommas(needed);
    toast(`بدهکار تراز شد: ${money(needed)} تومان`, "ok");
  }
  updateJeBalance();
}

function jeRow() {
  const rowCount = $$("#jeRows tbody tr").length + 1;
  const accOpts = state.accounts
    .map((a) => `<option value="${a.code}">${a.code} — ${esc(a.title)}</option>`)
    .join("");

  const detailOpts = [
    `<option value="">— تفصیلی شناور —</option>`,
    ...state.bankAccounts.map((b) => `<option value="${b.code}">[بانک] ${toFa(b.code)} — ${esc(b.title)}</option>`),
    ...state.customers.map((c) => `<option value="${c.code}">[مشتری] ${toFa(c.code)} — ${esc(c.title)}</option>`),
    ...state.suppliers.map((s) => `<option value="${s.code}">[تأمین‌کننده] ${toFa(s.code)} — ${esc(s.title)}</option>`),
  ].join("");

  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td class="row-idx">${toFa(rowCount)}</td>
    <td>
      <div class="input-with-action">
        <input class="jeAccCode" placeholder="کد" style="width:72px; text-align:center; font-weight:700;" maxlength="6" autocomplete="off">
        <button type="button" class="btn-cell-search btnLookupAcc" title="جستجوی حساب (F3)">🔍</button>
      </div>
    </td>
    <td><select class="jeAcc" style="width:100%; font-weight:600;">${accOpts}</select></td>
    <td>
      <div class="input-with-action">
        <select class="jeDetail" style="width:100%;">${detailOpts}</select>
        <button type="button" class="btn-cell-search btnLookupDetail" title="جستجوی تفصیلی (F3)">🔍</button>
      </div>
    </td>
    <td><input class="jeDesc" placeholder="شرح آرتیکل" autocomplete="off"></td>
    <td><input type="text" class="jeDr num" value="0" autocomplete="off"></td>
    <td>
      <div class="input-with-action">
        <input type="text" class="jeCr num" value="0" autocomplete="off">
        <button type="button" class="btn-cell-balance btnAutoBalance" title="تراز خودکار سطر (= یا F9)">⚖️</button>
      </div>
    </td>
    <td><button class="btn sm danger jeDel" title="حذف ردیف (Ctrl+Del)">×</button></td>`;

  const codeInp = tr.querySelector(".jeAccCode");
  const btnLookupAcc = tr.querySelector(".btnLookupAcc");
  const accSel = tr.querySelector(".jeAcc");
  const detailSel = tr.querySelector(".jeDetail");
  const btnLookupDetail = tr.querySelector(".btnLookupDetail");
  const descInp = tr.querySelector(".jeDesc");
  const drInp = tr.querySelector(".jeDr");
  const crInp = tr.querySelector(".jeCr");
  const btnAutoBalance = tr.querySelector(".btnAutoBalance");
  const delBtn = tr.querySelector(".jeDel");

  if (state.accounts[0]) {
    codeInp.value = state.accounts[0].code;
  }

  codeInp.oninput = () => {
    const code = codeInp.value.trim();
    const found = state.accounts.find((a) => a.code === code);
    if (found) {
      accSel.value = found.code;
    }
  };

  accSel.onchange = () => {
    codeInp.value = accSel.value;
  };

  const onNumInput = (e) => {
    const target = e.target;
    const pos = target.selectionStart;
    const oldLen = target.value.length;
    target.value = formatNumberWithCommas(target.value);
    const newLen = target.value.length;
    target.setSelectionRange(pos + (newLen - oldLen), pos + (newLen - oldLen));
    updateJeBalance();
  };

  drInp.oninput = onNumInput;
  crInp.oninput = onNumInput;

  // Auto-balance button click
  btnAutoBalance.onclick = () => applyAutoBalance(crInp, tr);

  // Fast Account Lookup trigger
  const triggerAccLookup = () => {
    openLookup("account", (acc) => {
      codeInp.value = acc.code;
      accSel.value = acc.code;
      detailSel.focus();
    }, codeInp.value, codeInp);
  };
  btnLookupAcc.onclick = triggerAccLookup;

  // Fast Detail Lookup trigger
  const triggerDetailLookup = () => {
    openLookup("detail", (det) => {
      detailSel.value = det.code;
      descInp.focus();
    }, "", detailSel);
  };
  btnLookupDetail.onclick = triggerDetailLookup;

  // Keyboard navigation & Excel-like flow
  codeInp.addEventListener("keydown", (e) => {
    if (e.key === "F3") {
      e.preventDefault();
      triggerAccLookup();
    } else if (e.key === "Enter" || e.key === "Tab") {
      if (e.key === "Enter") e.preventDefault();
      const code = codeInp.value.trim();
      const found = state.accounts.find((a) => a.code === code);
      if (found) {
        accSel.value = found.code;
        detailSel.focus();
      } else if (!code) {
        triggerAccLookup();
      } else {
        triggerAccLookup();
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const nextTr = tr.nextElementSibling;
      if (nextTr) {
        const nextInp = nextTr.querySelector(".jeAccCode");
        if (nextInp) nextInp.focus();
      } else {
        const newTr = jeRow();
        const nextInp = newTr.querySelector(".jeAccCode");
        if (nextInp) nextInp.focus();
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prevTr = tr.previousElementSibling;
      if (prevTr) {
        const prevInp = prevTr.querySelector(".jeAccCode");
        if (prevInp) prevInp.focus();
      }
    } else if (e.key === "Delete" && e.ctrlKey) {
      e.preventDefault();
      delBtn.click();
    }
  });

  accSel.addEventListener("keydown", (e) => {
    if (e.key === "F3") {
      e.preventDefault();
      triggerAccLookup();
    } else if (e.key === "Enter" || e.key === "Tab") {
      if (e.key === "Enter") e.preventDefault();
      detailSel.focus();
    }
  });

  detailSel.addEventListener("keydown", (e) => {
    if (e.key === "F3") {
      e.preventDefault();
      triggerDetailLookup();
    } else if (e.key === "Enter" || e.key === "Tab") {
      if (e.key === "Enter") e.preventDefault();
      descInp.focus();
    }
  });

  descInp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === "Tab") {
      if (e.key === "Enter") e.preventDefault();
      drInp.focus();
      drInp.select();
    } else if (e.key === "ArrowUp") {
      if (!descInp.value.trim()) {
        e.preventDefault();
        const prevTr = tr.previousElementSibling;
        if (prevTr && prevTr.querySelector(".jeDesc") && prevTr.querySelector(".jeDesc").value.trim()) {
          descInp.value = prevTr.querySelector(".jeDesc").value;
        } else {
          descInp.value = $("#jeDesc").value || "";
        }
      }
    } else if (e.key === "Delete" && e.ctrlKey) {
      e.preventDefault();
      delBtn.click();
    }
  });

  drInp.addEventListener("keydown", (e) => {
    if (e.key === "=" || e.key === "F9") {
      e.preventDefault();
      applyAutoBalance(drInp, tr);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const val = parseFormattedNumber(drInp.value || 0);
      if (val > 0) {
        // Debit entered -> jump straight to next row
        const nextTr = tr.nextElementSibling;
        if (nextTr) {
          const nextCode = nextTr.querySelector(".jeAccCode");
          if (nextCode) nextCode.focus();
        } else {
          const newTr = jeRow();
          const nextCode = newTr.querySelector(".jeAccCode");
          if (nextCode) nextCode.focus();
        }
      } else {
        // Zero debit -> move to credit
        crInp.focus();
        crInp.select();
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const nextTr = tr.nextElementSibling;
      if (nextTr && nextTr.querySelector(".jeDr")) nextTr.querySelector(".jeDr").focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prevTr = tr.previousElementSibling;
      if (prevTr && prevTr.querySelector(".jeDr")) prevTr.querySelector(".jeDr").focus();
    } else if (e.key === "Delete" && e.ctrlKey) {
      e.preventDefault();
      delBtn.click();
    }
  });

  crInp.addEventListener("keydown", (e) => {
    if (e.key === "=" || e.key === "F9") {
      e.preventDefault();
      applyAutoBalance(crInp, tr);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const nextTr = tr.nextElementSibling;
      if (nextTr) {
        const nextCode = nextTr.querySelector(".jeAccCode");
        if (nextCode) nextCode.focus();
      } else {
        const newTr = jeRow();
        const nextCode = newTr.querySelector(".jeAccCode");
        if (nextCode) nextCode.focus();
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const nextTr = tr.nextElementSibling;
      if (nextTr && nextTr.querySelector(".jeCr")) nextTr.querySelector(".jeCr").focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prevTr = tr.previousElementSibling;
      if (prevTr && prevTr.querySelector(".jeCr")) prevTr.querySelector(".jeCr").focus();
    } else if (e.key === "Delete" && e.ctrlKey) {
      e.preventDefault();
      delBtn.click();
    }
  });

  delBtn.onclick = () => {
    tr.remove();
    reindexJeRows();
    updateJeBalance();
  };

  $("#jeRows tbody").appendChild(tr);
  updateJeBalance();
  return tr;
}

function updateJeBalance() {
  let dr = 0, cr = 0;
  $$("#jeRows tbody tr").forEach((tr) => {
    dr += parseFormattedNumber(tr.querySelector(".jeDr").value || 0);
    cr += parseFormattedNumber(tr.querySelector(".jeCr").value || 0);
  });
  const diff = Math.abs(dr - cr);
  
  const totalDrEl = $("#jeTotalDr");
  const totalCrEl = $("#jeTotalCr");
  if (totalDrEl) totalDrEl.textContent = money(dr);
  if (totalCrEl) totalCrEl.textContent = money(cr);

  const el = $("#jeBalance");
  if (el) {
    if (diff < 0.01 && (dr > 0 || cr > 0)) {
      el.textContent = `تراز دوبل برقرار است ✔`;
      el.className = "badge ok";
    } else if (diff < 0.01) {
      el.textContent = `تراز: ۰ تومان`;
      el.className = "badge ok";
    } else {
      el.textContent = `اختلاف تراز: ${money(diff)} تومان`;
      el.className = "badge bad";
    }
  }
}

function renderTree(nodes) {
  return nodes
    .map((n) => {
      const head =
        n.level === "group" ? `<div class="g">${n.code} — ${esc(n.title)}</div>`
        : n.level === "general" ? `<div class="k">${n.code} — ${esc(n.title)}</div>`
        : `<div class="s"><span>${esc(n.title)}</span><span class="muted">${toFa(n.code)}</span></div>`;
      return head + (n.children && n.children.length ? renderTree(n.children) : "");
    })
    .join("");
}

async function loadLedger() {
  if (!state.accounts.length) await loadShared();
  $("#accountTree").innerHTML = renderTree(state.tree);

  const drafts = $("#jeDrafts").checked;
  const entries = await api(
    `/tenants/${state.tenant}/entries?fiscal_year_id=${state.fy}&include_drafts=${drafts}`
  );
  $("#entriesBody").innerHTML =
    entries
      .map((e) => {
        const canPost = ["draft", "approved"].includes(e.status);
        const canDel = e.status === "draft";
        return `<tr>
          <td>${toFa(e.entry_number)}</td>
          <td>${toFa(e.entry_date)}</td>
          <td>${toFa(e.entry_date_jalali || "")}</td>
          <td>${esc(e.description)}</td>
          <td>${esc(e.source_module)}</td>
          <td>${badge(e.status, STATUS_LABEL)}</td>
          <td class="num">${money(e.total_amount)}</td>
          <td class="actions">
            <button class="btn sm ghost" data-view-entry="${e.id}">نمایش</button>
            <button class="btn sm ghost" data-docflow-je="${e.id}" title="ارتباط و پیگیری اسناد">🔗 ارتباط اسناد</button>
            ${canPost && e.status === "approved" ? `<button class="btn sm info" data-post="${e.id}">قید</button>` : ""}
            ${canPost && e.status === "draft" ? `<button class="btn sm info" data-appr="${e.id}">تایید</button>` : ""}
            ${canDel ? `<button class="btn sm danger" data-del="${e.id}">حذف</button>` : ""}
          </td>
        </tr>`;
      })
      .join("") || `<tr><td colspan="8" class="empty">سندی یافت نشد.</td></tr>`;

  $$("#entriesBody [data-view-entry]").forEach((b) => (b.onclick = () => showEntry(b.dataset.viewEntry)));
  $$("#entriesBody [data-docflow-je]").forEach((b) => (b.onclick = () => openDocFlow("journal_entry", b.dataset.docflowJe)));
  $$("#entriesBody [data-post]").forEach((b) => (b.onclick = () => setEntryStatus(b.dataset.post, "permanent")));
  $$("#entriesBody [data-appr]").forEach((b) => (b.onclick = () => setEntryStatus(b.dataset.appr, "approved")));
  $$("#entriesBody [data-del]").forEach((b) => (b.onclick = () => delEntry(b.dataset.del)));

  await loadTrialBalance();
  await loadStatements();
}

async function showEntry(id) {
  const e = await api(`/tenants/${state.tenant}/entries/${id}`);
  const lines = (e.items || [])
    .map(
      (it, idx) => `<tr>
        <td class="row-idx">${toFa(idx + 1)}</td>
        <td style="font-weight:700;">${toFa(it.account_code)}</td>
        <td>${esc(it.account_title)}</td>
        <td>${it.sub_ledger_code ? `${toFa(it.sub_ledger_code)} — ${esc(it.sub_ledger_title || "")}` : "—"}</td>
        <td>${esc(it.description || "")}</td>
        <td class="num">${money(it.debit)}</td>
        <td class="num">${money(it.credit)}</td>
      </tr>`
    )
    .join("");
  const dr = (e.items || []).reduce((a, i) => a + Number(i.debit || 0), 0);
  const cr = (e.items || []).reduce((a, i) => a + Number(i.credit || 0), 0);
  const isBalanced = Math.abs(dr - cr) < 0.01;

  openModal(`سند حسابداری شماره ${toFa(e.entry_number)}`, `
    <div class="voucher-sheet">
      <div class="voucher-header">
        <div class="voucher-header-top">
          <div class="voucher-company">شرکت فناوری مالی آربین پارس (سهامی خاص)</div>
          <div class="badge ${e.status === "approved" ? "ok" : "warn"}">${STATUS_LABEL[e.status] || e.status}</div>
        </div>
        <div class="voucher-title">سند حسابداری دوطرفه (دوبل)</div>
        <div class="voucher-meta-grid">
          <div><strong>شماره سند:</strong> ${toFa(e.entry_number)}</div>
          <div><strong>شماره عطف:</strong> ${toFa(e.entry_number)}</div>
          <div><strong>تاریخ سند:</strong> ${toFa(e.entry_date_jalali || e.entry_date)}</div>
          <div><strong>سیستم صادرکننده:</strong> ${esc(e.source_module || "حسابداری مالی")}</div>
        </div>
        <div style="margin-top:8px; font-size:12.5px;">
          <strong>شرح کلی سند:</strong> ${esc(e.description || "—")}
        </div>
      </div>

      <div class="table-wrap">
        <table class="arbin-grid">
          <thead>
            <tr>
              <th style="width:32px;">#</th>
              <th style="width:80px;">کد معین</th>
              <th>عنوان حساب معین</th>
              <th>تفصیلی شناور</th>
              <th>شرح آرتیکل</th>
              <th class="num" style="width:130px;">بدهکار (تومان)</th>
              <th class="num" style="width:130px;">بستانکار (تومان)</th>
            </tr>
          </thead>
          <tbody>${lines}</tbody>
          <tfoot>
            <tr>
              <td colspan="5" style="text-align:right;">جمع کل سند:</td>
              <td class="num">${money(dr)}</td>
              <td class="num">${money(cr)}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      <div class="voucher-signatures">
        <div class="sig-box">تنظیم‌کننده</div>
        <div class="sig-box">رسیدگی‌کننده (حسابدار)</div>
        <div class="sig-box">مدیر مالی</div>
        <div class="sig-box">مدیرعامل</div>
      </div>
    </div>

    <div class="actions" style="margin-top:14px; justify-content:space-between;">
      <div>
        <span class="badge ${isBalanced ? "ok" : "bad"}">
          ${isBalanced ? "سند کاملاً متوازن است ✔" : "اختلاف تراز: " + money(Math.abs(dr - cr)) + " تومان"}
        </span>
      </div>
      <div class="actions">
        <button class="btn sm" id="btnDocFlowEntry" style="background:#fef3c7; border-color:#d97706; color:#92400e;">🔗 پیگیری و ارتباط اسناد</button>
        <button class="btn sm ghost" id="btnPrintEntry">🖨️ چاپ سند رسمی (A4)</button>
      </div>
    </div>`);

  $("#btnDocFlowEntry").onclick = () => {
    closeModal();
    openDocFlow("journal_entry", id);
  };

  $("#btnPrintEntry").onclick = () => {
    $("#printArea").innerHTML = $("#modalBody").innerHTML;
    window.print();
  };
}

/* ---------------- 2.5 Account Drill-Down (مرور جامع حساب‌ها) ---------------- */
function updateDrillDownBreadcrumb() {
  const steps = [
    { id: "group", label: "۱. گروه حساب‌ها" },
    { id: "general", label: "۲. کل: " + (state.drilldown.groupTitle || "") },
    { id: "subsidiary", label: "۳. معین: " + (state.drilldown.generalTitle || "") },
    { id: "statement", label: "۴. گردش اسناد: " + (state.drilldown.subsidiaryTitle || "") },
  ];

  const html = [];
  const cur = state.drilldown.level;
  
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    const isPast = (cur === "general" && i < 1) || 
                   (cur === "subsidiary" && i < 2) || 
                   (cur === "statement" && i < 3);
    const isCur = cur === s.id;
    if (isCur || isPast) {
      if (html.length > 0) html.push(`<span class="drilldown-sep">❯</span>`);
      html.push(`<span class="drilldown-step ${isCur ? "active" : ""}" data-dd-step="${s.id}">${s.label}</span>`);
    }
  }

  const bc = $("#ddBreadcrumb");
  if (bc) {
    bc.innerHTML = html.join("");
    $$("#ddBreadcrumb [data-dd-step]").forEach((el) => {
      el.onclick = () => {
        state.drilldown.level = el.dataset.ddStep;
        loadDrillDown();
      };
    });
  }
}

async function loadDrillDown() {
  updateDrillDownBreadcrumb();
  const lvl = state.drilldown.level;

  try {
    if (lvl === "group") {
      const data = await api(`/tenants/${state.tenant}/reports/trial-balance?fiscal_year_id=${state.fy}&level=group`);
      renderDrillDownTable("گروه", data, (row) => {
        state.drilldown.groupCode = row.code;
        state.drilldown.groupTitle = row.title;
        state.drilldown.level = "general";
        loadDrillDown();
      });
    } else if (lvl === "general") {
      const allGen = await api(`/tenants/${state.tenant}/reports/trial-balance?fiscal_year_id=${state.fy}&level=general`);
      const data = allGen.filter((g) => g.code.startsWith(state.drilldown.groupCode));
      renderDrillDownTable("کل", data, (row) => {
        state.drilldown.generalCode = row.code;
        state.drilldown.generalTitle = row.title;
        state.drilldown.level = "subsidiary";
        loadDrillDown();
      });
    } else if (lvl === "subsidiary") {
      const allSubs = await api(`/tenants/${state.tenant}/reports/trial-balance?fiscal_year_id=${state.fy}&level=subsidiary`);
      const data = allSubs.filter((s) => s.code.startsWith(state.drilldown.generalCode));
      renderDrillDownTable("معین", data, (row) => {
        state.drilldown.subsidiaryCode = row.code;
        state.drilldown.subsidiaryTitle = row.title;
        state.drilldown.level = "statement";
        loadDrillDown();
      });
    } else if (lvl === "statement") {
      const stmt = await api(`/tenants/${state.tenant}/reports/account-statement?fiscal_year_id=${state.fy}&account_code=${state.drilldown.subsidiaryCode}`);
      renderDrillDownStatement(stmt);
    }
  } catch (err) {
    toast(err.message, "error");
  }
}

function renderDrillDownTable(levelName, rows, onSelect) {
  let totDr = 0, totCr = 0, totBalDr = 0, totBalCr = 0;
  rows.forEach((r) => {
    totDr += Number(r.total_debit || r.turnover_debit || 0);
    totCr += Number(r.total_credit || r.turnover_credit || 0);
    totBalDr += Number(r.balance_debit || 0);
    totBalCr += Number(r.balance_credit || 0);
  });

  const ddTotalDr = $("#ddTotalDr");
  const ddTotalCr = $("#ddTotalCr");
  const ddBalance = $("#ddBalance");
  if (ddTotalDr) ddTotalDr.innerHTML = `${money(totDr)} <span class="unit">تومان</span>`;
  if (ddTotalCr) ddTotalCr.innerHTML = `${money(totCr)} <span class="unit">تومان</span>`;
  if (ddBalance) ddBalance.innerHTML = `${money(Math.abs(totBalDr - totBalCr))} <span class="unit">${totBalDr >= totBalCr ? "بد" : "بس"}</span>`;

  $("#ddThead").innerHTML = `
    <tr>
      <th style="width:100px;">کد حساب</th>
      <th>عنوان حساب</th>
      <th style="width:90px;">سطح</th>
      <th class="num" style="width:130px;">گردش بدهکار</th>
      <th class="num" style="width:130px;">گردش بستانکار</th>
      <th class="num" style="width:130px;">مانده بدهکار</th>
      <th class="num" style="width:130px;">مانده بستانکار</th>
      <th style="width:100px;">عملیات</th>
    </tr>`;

  if (!rows.length) {
    $("#ddBody").innerHTML = `<tr><td colspan="8" class="empty">موردی یافت نشد.</td></tr>`;
    $("#ddFoot").innerHTML = "";
    return;
  }

  $("#ddBody").innerHTML = rows
    .map(
      (r, idx) => `
    <tr data-dd-row="${idx}">
      <td style="font-weight:700;">${toFa(r.code)}</td>
      <td><strong>${esc(r.title)}</strong></td>
      <td><span class="badge info">${levelName}</span></td>
      <td class="num">${money(r.total_debit || r.turnover_debit || 0)}</td>
      <td class="num">${money(r.total_credit || r.turnover_credit || 0)}</td>
      <td class="num">${money(r.balance_debit || 0)}</td>
      <td class="num">${money(r.balance_credit || 0)}</td>
      <td><button class="btn sm ghost" data-dd-btn="${idx}">ورود ❯</button></td>
    </tr>`
    )
    .join("");

  $("#ddFoot").innerHTML = `
    <tr>
      <td colspan="3" style="text-align:right;">جمع کل:</td>
      <td class="num">${money(totDr)}</td>
      <td class="num">${money(totCr)}</td>
      <td class="num">${money(totBalDr)}</td>
      <td class="num">${money(totBalCr)}</td>
      <td></td>
    </tr>`;

  rows.forEach((r, idx) => {
    const tr = $(`#ddBody tr[data-dd-row="${idx}"]`);
    if (tr) {
      tr.onclick = () => onSelect(r);
    }
  });
}

function renderDrillDownStatement(stmt) {
  const rows = stmt.lines || stmt.items || [];
  let totDr = 0, totCr = 0;
  rows.forEach((r) => {
    totDr += Number(r.debit || 0);
    totCr += Number(r.credit || 0);
  });

  const ddTotalDr = $("#ddTotalDr");
  const ddTotalCr = $("#ddTotalCr");
  const ddBalance = $("#ddBalance");
  if (ddTotalDr) ddTotalDr.innerHTML = `${money(totDr)} <span class="unit">تومان</span>`;
  if (ddTotalCr) ddTotalCr.innerHTML = `${money(totCr)} <span class="unit">تومان</span>`;
  if (ddBalance) ddBalance.innerHTML = `${money(Math.abs(totDr - totCr))} <span class="unit">${totDr >= totCr ? "بد" : "بس"}</span>`;

  $("#ddThead").innerHTML = `
    <tr>
      <th style="width:80px;">شماره سند</th>
      <th style="width:110px;">تاریخ سند</th>
      <th>شرح آرتیکل</th>
      <th style="width:140px;">تفصیلی شناور</th>
      <th class="num" style="width:130px;">بدهکار</th>
      <th class="num" style="width:130px;">بستانکار</th>
      <th class="num" style="width:130px;">مانده لحظه‌ای</th>
      <th style="width:90px;">مشاهده</th>
    </tr>`;

  if (!rows.length) {
    $("#ddBody").innerHTML = `<tr><td colspan="8" class="empty">هیچ سندی برای این حساب معین یافت نشد.</td></tr>`;
    $("#ddFoot").innerHTML = "";
    return;
  }

  $("#ddBody").innerHTML = rows
    .map(
      (r) => {
        const bal = r.running_balance != null ? r.running_balance : (r.balance || 0);
        return `
    <tr data-stmt-entry="${r.entry_id || ''}" style="cursor:pointer;">
      <td style="font-weight:700;">${toFa(r.entry_number)}</td>
      <td>${toFa(r.entry_date_jalali || r.entry_date)}</td>
      <td>${esc(r.description || "")}</td>
      <td>${r.sub_ledger_code ? `${toFa(r.sub_ledger_code)} — ${esc(r.sub_ledger_title || "")}` : "—"}</td>
      <td class="num">${money(r.debit)}</td>
      <td class="num">${money(r.credit)}</td>
      <td class="num" style="font-weight:700;">${money(Math.abs(bal))} ${bal >= 0 ? "بد" : "بس"}</td>
      <td>${r.entry_id ? `<button class="btn sm" data-view-entry="${r.entry_id}">سند 📄</button>` : "—"}</td>
    </tr>`;
      }
    )
    .join("");

  $("#ddFoot").innerHTML = `
    <tr>
      <td colspan="4" style="text-align:right;">جمع گردش:</td>
      <td class="num">${money(totDr)}</td>
      <td class="num">${money(totCr)}</td>
      <td class="num" style="font-weight:700;">${money(Math.abs(totDr - totCr))}</td>
      <td></td>
    </tr>`;

  $$("#ddBody [data-view-entry]").forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      showEntry(btn.dataset.viewEntry);
    };
  });

  $$("#ddBody tr[data-stmt-entry]").forEach((tr) => {
    tr.ondblclick = () => {
      showEntry(tr.dataset.stmtEntry);
    };
  });
}


function showPayslipModal(s) {
  const b = s.breakdown || {};
  const row = (k, v) =>
    `<tr><td>${k}</td><td class="num">${typeof v === "number" ? money(v) : esc(v == null || v === "" ? "—" : v)}</td></tr>`;
  const num = (x) => (typeof x === "number" ? x : null);
  openModal(`فیش حقوقی — ${esc(s.full_name)}`, `
    <p class="muted">${esc(s.job_title || "")} ${s.national_id ? `— کد ملی ${toFa(s.national_id)}` : ""}${
      state.lastRunLabel ? ` — ماه ${esc(state.lastRunLabel)}` : ""
    }</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>شرح</th><th class="num">مبلغ / مقدار</th></tr></thead>
        <tbody>
          ${row("حقوق پایه واقعی (کارکرد)", num(b.actual_base))}
          ${row("اضافه‌کاری", num(b.overtime_pay))}
          ${row("حق مسکن", num(b.housing_allowance))}
          ${row("بن خواربار", num(b.grocery_allowance))}
          ${row("حق اولاد", num(b.child_allowance))}
          ${row("ناخالص", s.gross_salary)}
          ${row("بیمه سهم کارمند ۷٪", num(b.employee_insurance_7pct) != null ? -b.employee_insurance_7pct : -s.employee_insurance)}
          ${row("مشمول مالیات", num(b.taxable_income))}
          ${row("معافیت مالیاتی ماهانه", num(b.tax_exemption_ceiling))}
          ${row("مالیات ماده ۸۴", -Math.abs(s.income_tax))}
          ${row("بیمه سهم کارفرما ۲۳٪", num(b.employer_insurance_23pct) != null ? b.employer_insurance_23pct : s.employer_insurance)}
          ${row("خالص قابل پرداخت", s.net_payable)}
          ${s.bank_shaba ? `<tr><td>شماره شبا</td><td class="num">${toFa(s.bank_shaba)}</td></tr>` : ""}
        </tbody>
      </table>
    </div>
    <div class="actions" style="margin-top:12px;">
      <button class="btn sm ghost" id="btnPrintPayslip">چاپ فیش</button>
    </div>`);
  $("#btnPrintPayslip").onclick = () => {
    $("#printArea").innerHTML = $("#modalBody").innerHTML;
    window.print();
  };
}

async function setEntryStatus(id, status) {
  try {
    await api(`/tenants/${state.tenant}/entries/${id}/status`, { method: "POST", body: { status } });
    toast("وضعیت سند به‌روزرسانی شد.");
    loadLedger();
  } catch (e) { toast(e.message, "error"); }
}

async function delEntry(id) {
  if (!confirm("سند پیش‌نویس حذف شود؟")) return;
  try {
    await api(`/tenants/${state.tenant}/entries/${id}`, { method: "DELETE" });
    toast("سند حذف شد.");
    loadLedger();
  } catch (e) { toast(e.message, "error"); }
}

async function loadTrialBalance() {
  const level = $("#tbLevel").value;
  const rows = await api(
    `/tenants/${state.tenant}/reports/trial-balance?level=${level}&fiscal_year_id=${state.fy}`
  );
  const active = rows.filter((r) => r.total_debit || r.total_credit);
  $("#tbBody").innerHTML =
    active
      .map(
        (r) => `<tr>
          <td>${toFa(r.code)}</td><td>${esc(r.title)}</td>
          <td class="num">${money(r.total_debit)}</td>
          <td class="num">${money(r.total_credit)}</td>
          <td class="num">${money(r.balance_debit)}</td>
          <td class="num">${money(r.balance_credit)}</td>
        </tr>`
      )
      .join("") || `<tr><td colspan="6" class="empty">گردشی ثبت نشده است.</td></tr>`;
  const sum = (k) => active.reduce((a, r) => a + r[k], 0);
  $("#tbFoot").innerHTML = `<tr>
      <td colspan="2">جمع</td>
      <td class="num">${money(sum("total_debit"))}</td>
      <td class="num">${money(sum("total_credit"))}</td>
      <td class="num">${money(sum("balance_debit"))}</td>
      <td class="num">${money(sum("balance_credit"))}</td>
    </tr>`;
}

async function loadStatements() {
  const [inc, bs] = await Promise.all([
    api(`/tenants/${state.tenant}/reports/income-statement?fiscal_year_id=${state.fy}`),
    api(`/tenants/${state.tenant}/reports/balance-sheet?fiscal_year_id=${state.fy}`),
  ]);

  $("#isBody").innerHTML = `
    <tr><td>درآمدها (گروه ۶)</td><td class="num">${money(inc.total_revenue)}</td></tr>
    <tr><td>بهای تمام شده (۷۰)</td><td class="num">${money(inc.total_cogs)}</td></tr>
    <tr><td>سود ناخالص</td><td class="num">${money(inc.gross_profit)}</td></tr>
    ${inc.operating_expenses
      .map((e) => `<tr><td class="muted">— ${esc(e.title)}</td><td class="num">${money(e.amount)}</td></tr>`)
      .join("")}
    <tr><td>مجموع هزینه‌های عملیاتی</td><td class="num">${money(inc.total_expenses)}</td></tr>`;
  $("#isFoot").innerHTML = `<tr><td>سود خالص دوره</td><td class="num">${money(inc.net_profit)}</td></tr>`;

  $("#bsBody").innerHTML = `
    <tr><td>دارایی‌های جاری</td><td class="num">${money(bs.current_assets)}</td></tr>
    <tr><td>دارایی‌های غیرجاری</td><td class="num">${money(bs.fixed_assets)}</td></tr>
    <tr><td>بدهی‌ها</td><td class="num">${money(bs.total_liabilities)}</td></tr>
    <tr><td>سرمایه و اندوخته‌ها</td><td class="num">${money(bs.base_equity)}</td></tr>
    <tr><td>سود جاری سال</td><td class="num">${money(bs.current_year_profit)}</td></tr>`;
  $("#bsFoot").innerHTML = `<tr><td>${bs.is_balanced ? "ترازنامه متوازن ✔" : "ناهمتراز ✖"}</td>
      <td class="num">${money(bs.total_equity_and_liabilities)}</td></tr>`;
}

async function runAccountStatement() {
  const code = $("#asCode").value.trim();
  if (!code) return toast("کد حساب را وارد کنید.", "error");
  try {
    const st = await api(
      `/tenants/${state.tenant}/reports/account-statement?account_code=${code}&fiscal_year_id=${state.fy}`
    );
    $("#asBody").innerHTML =
      st.lines
        .map(
          (l) => `<tr>
            <td>${toFa(l.entry_number)}</td>
            <td>${toFa(l.entry_date_jalali || l.entry_date)}</td>
            <td>${esc(l.description)}</td>
            <td class="num">${money(l.debit)}</td>
            <td class="num">${money(l.credit)}</td>
            <td class="num">${money(l.running_balance)}</td>
          </tr>`
        )
        .join("") || `<tr><td colspan="6" class="empty"> Movی ثبت نشده است.</td></tr>`;
    $("#asFoot").innerHTML = `<tr><td colspan="3">جمع گردش ${st.account_title || code}</td>
        <td class="num">${money(st.total_debit)}</td>
        <td class="num">${money(st.total_credit)}</td>
        <td class="num">${money(st.closing_balance)}</td></tr>`;
  } catch (e) { toast(e.message, "error"); }
}

async function closeFY() {
  if (!confirm("سال مالی بسته شود؟ پس از آن ثبت سند در این سال ممکن نیست.")) return;
  try {
    const r = await api(`/tenants/${state.tenant}/fiscal-years/${state.fy}/close`, { method: "POST", body: {} });
    $("#fyResult").innerHTML = `<div class="badge ok">سال مالی بسته شد</div>
      <p>سود/زیان خالص: <strong>${money(r.net_income)}</strong> تومان<br>
      اسناد اختتامیه: ${toFa((r.entry_ids || []).length)} ردیف</p>`;
    toast("سند اختتامیه با موفقیت صادر شد.");
  } catch (e) { toast(e.message, "error"); }
}

async function openFY() {
  try {
    const r = await api(`/tenants/${state.tenant}/fiscal-years/${state.fy}/opening`, { method: "POST", body: {} });
    $("#fyResult").innerHTML = r.entry_id
      ? `<div class="badge ok">سند افتتاحیه ثبت شد</div><p>شناسه سند: ${toFa(r.entry_id.slice(0, 8))}</p>`
      : `<div class="badge gray">موردی برای انتقال وجود نداشت</div>`;
    toast("سند افتتاحیه بررسی شد.");
  } catch (e) { toast(e.message, "error"); }
}

/* ---------------- 2.6 Document Flow & Audit Trail (ارتباط و پیگیری اسناد) ---------------- */
window.openDocFlow = function (entityType, entityId) {
  state.activeDocFlow = { entityType, entityId };
  go("docflow");
};

async function loadDocumentFlow() {
  try {
    const recentList = await api(`/tenants/${state.tenant}/document-flow/recent`);
    const select = $("#dfRecentSelect");
    if (recentList && recentList.length) {
      select.innerHTML = recentList
        .map(
          (item) => `<option value="${item.entity_type}:${item.entity_id}">
            ${esc(item.title)} — ${toFa(item.date || "")} (${money(item.amount)} تومان)
          </option>`
        )
        .join("");
    } else {
      select.innerHTML = `<option value="">هیچ سندی در پایگاه داده یافت نشد</option>`;
    }

    let targetType = "invoice";
    let targetId = null;

    if (state.activeDocFlow && state.activeDocFlow.entityId) {
      targetType = state.activeDocFlow.entityType;
      targetId = state.activeDocFlow.entityId;
      const matchVal = `${targetType}:${targetId}`;
      if (select.querySelector(`option[value="${matchVal}"]`)) {
        select.value = matchVal;
      }
    } else if (recentList && recentList.length) {
      targetType = recentList[0].entity_type;
      targetId = recentList[0].entity_id;
      select.value = `${targetType}:${targetId}`;
    }

    if (!targetId) {
      $("#dfSummaryBar").style.display = "none";
      $("#dfStepper").innerHTML = `<div style="padding:16px; text-align:center; color:var(--text-muted); width:100%;">سندی برای نمایش ثبت نشده است. ابتدا یک فاکتور یا سند حسابداری ثبت کنید.</div>`;
      $("#dfCardsContainer").innerHTML = "";
      $("#dfAuditTableBody").innerHTML = `<tr><td colspan="5" class="empty">سابقه‌ای ثبت نشده است.</td></tr>`;
      return;
    }

    $("#dfSummaryBar").style.display = "grid";
    const flow = await api(`/tenants/${state.tenant}/document-flow/${targetType}/${targetId}`);
    renderDocumentFlow(flow);
  } catch (err) {
    console.error("Document Flow Load Error:", err);
    toast("خطا در بارگذاری زنجیره اسناد: " + err.message, "error");
  }
}

function renderDocumentFlow(flow) {
  const sum = flow.summary || {};
  $("#dfRootTitle").textContent = sum.root_title || "—";
  $("#dfPartyName").textContent = sum.party_name || "—";
  $("#dfAmount").textContent = sum.amount_formatted ? toFa(sum.amount_formatted) : money(sum.amount) + " تومان";
  $("#dfStartDate").textContent = toFa(sum.date || sum.start_date || "—");
  $("#dfNodeCount").textContent = toFa(sum.node_count || 0) + " سند متصل";

  const stBadge = $("#dfStatusBadge");
  const isComplete = sum.overall_status === "completed" || (sum.overall_status && sum.overall_status.includes("تایید"));
  stBadge.textContent = sum.overall_status ? esc(sum.overall_status) : (isComplete ? "تکمیل شده ✔" : "در جریان ⏳");
  stBadge.className = "badge " + (isComplete ? "ok" : "warn");

  // 1. Render Stages Stepper
  const stages = flow.stages || [];
  let stepperHtml = "";
  stages.forEach((st, idx) => {
    let icon = "⚪";
    if (st.state === "completed") icon = "✔";
    else if (st.state === "in_progress") icon = "⏳";
    else if (st.state === "skipped") icon = "—";

    stepperHtml += `
      <div class="df-step-item ${st.state}">
        <div class="df-step-circle">${icon}</div>
        <div class="df-step-name">${esc(st.title)}</div>
        <div class="df-step-desc">${esc(st.description || "")}</div>
        <div class="df-step-badge">${esc(st.badge || st.state_label || "")}</div>
      </div>
    `;
    if (idx < stages.length - 1) {
      const isConnCompleted = st.state === "completed";
      stepperHtml += `<div class="df-step-connector ${isConnCompleted ? "completed" : ""}"></div>`;
    }
  });
  $("#dfStepper").innerHTML = stepperHtml;

  // 2. Render Cards Flow
  const nodes = flow.nodes || [];
  let cardsHtml = "";
  nodes.forEach((n, idx) => {
    const isRoot = n.id === flow.root_id || idx === 0;
    let headCls = "inv";
    if (n.type === "inventory") headCls = "wh";
    else if (n.type === "journal_voucher" || n.type === "journal_entry") headCls = "jv";
    else if (n.type === "cheque" || n.type === "treasury") headCls = "chk";
    else if (n.type === "taxpayer") headCls = "tax";

    let rowsHtml = "";
    if (n.details && Array.isArray(n.details)) {
      rowsHtml = n.details
        .map((d) => `<div class="df-row"><span class="k">${esc(d.label)}:</span><span class="v">${esc(toFa(d.value))}</span></div>`)
        .join("");
    } else if (n.data) {
      if (n.data.number) rowsHtml += `<div class="df-row"><span class="k">شماره سند:</span><span class="v">${toFa(n.data.number)}</span></div>`;
      if (n.data.date) rowsHtml += `<div class="df-row"><span class="k">تاریخ:</span><span class="v">${toFa(n.data.date)}</span></div>`;
      if (n.data.party) rowsHtml += `<div class="df-row"><span class="k">طرف حساب:</span><span class="v">${esc(n.data.party)}</span></div>`;
      if (n.data.amount) rowsHtml += `<div class="df-row"><span class="k">مبلغ:</span><span class="v">${money(n.data.amount)} تومان</span></div>`;
    }

    let jumpBtn = "";
    if (n.jump_target) {
      const jt = n.jump_target;
      jumpBtn = `<button class="df-jump-btn" onclick="handleDocFlowJump('${jt.view}', '${jt.id}')">🔎 ${esc(jt.label || "مشاهده")}</button>`;
    } else if (n.type === "journal_voucher" || n.type === "journal_entry") {
      jumpBtn = `<button class="df-jump-btn" onclick="showEntry('${n.id}')">🔎 مشاهده سند دوبل</button>`;
    } else if (n.type === "invoice") {
      jumpBtn = `<button class="df-jump-btn" onclick="go('sales'); showInvoice('${n.id}');">🔎 مشاهده فاکتور</button>`;
    } else if (n.type === "inventory") {
      jumpBtn = `<button class="df-jump-btn" onclick="go('inventory');">📦 کاردکس انبار</button>`;
    } else if (n.type === "cheque") {
      jumpBtn = `<button class="df-jump-btn" onclick="go('treasury');">💰 خزانه‌داری و چک</button>`;
    }

    const badgeText = n.status_label || n.badge || "";
    cardsHtml += `
      <div class="df-card-node ${isRoot ? "root-node" : ""}">
        <div class="df-card-head ${headCls}">
          <div class="df-card-title">
            <span>${n.icon || "📄"}</span>
            <span>${esc(n.title)}</span>
          </div>
          ${badgeText ? `<span class="badge info">${esc(badgeText)}</span>` : ""}
        </div>
        ${n.subtitle ? `<div style="font-size:11px; color:var(--text-muted); padding:4px 10px 0 10px;">${esc(n.subtitle)}</div>` : ""}
        <div class="df-card-body">
          ${rowsHtml}
        </div>
        ${jumpBtn ? `<div class="df-card-foot">${jumpBtn}</div>` : ""}
      </div>
    `;

    if (idx < nodes.length - 1) {
      cardsHtml += `<div class="df-connector-badge">←</div>`;
    }
  });
  $("#dfCardsContainer").innerHTML = cardsHtml;

  // 3. Render Audit Trail
  const audit = flow.audit_trail || [];
  if (audit.length) {
    $("#dfAuditTableBody").innerHTML = audit
      .map(
        (a) => `
        <tr>
          <td style="font-family:monospace; direction:ltr; text-align:right;">${toFa(a.timestamp || a.created_at || "—")}</td>
          <td><strong>${esc(a.user || a.user_id || "سیستم")}</strong></td>
          <td><span class="df-audit-action-badge ${(a.action || a.action_type || "create").toLowerCase()}">${esc(a.action || a.action_type)}</span></td>
          <td>${esc(a.entity || a.entity_type || "سند")}</td>
          <td>${esc(a.description || a.details || "—")}</td>
        </tr>
      `
      )
      .join("");
  } else {
    $("#dfAuditTableBody").innerHTML = `<tr><td colspan="5" class="empty">هیچ سابقه‌ای در ردپای عملیات ثبت نشده است.</td></tr>`;
  }
}

window.handleDocFlowJump = function(view, id) {
  if (view === "ledger") {
    showEntry(id);
  } else if (view === "invoicing" || view === "sales") {
    go("sales");
    showInvoice(id);
  } else if (view === "inventory") {
    go("inventory");
  } else if (view === "treasury") {
    go("treasury");
  } else {
    go(view);
  }
};

/* ---------------- 3. Treasury ---------------- */
async function loadTreasury() {
  if (!state.customers.length) await loadShared();
  fillSelect("#chCustomer", state.customers, "id", "title", "انتخاب مشتری");
  fillSelect("#isPayee", state.payees, "id", "title", "انتخاب ذینفع");
  fillSelect("#isBankAcc", state.bankAccounts, "id", "title", "انتخاب حساب بانکی");
  fillSelect("#txBank", state.bankAccounts, "id", "title", "صندوق نقد (بدون بانک)");
  fillSelect(
    "#txParty",
    state.customers.concat(state.suppliers),
    "id",
    "title",
    "بدون طرف حساب"
  );
  const txDate = $("#txDate");
  if (txDate && !txDate.value) txDate.value = todayISO();

  const type = $("#chequeFilter").value;
  const cheques = await api(
    `/tenants/${state.tenant}/treasury/cheques${type ? "?cheque_type=" + type : ""}`
  );  $("#chequesBody").innerHTML =
    cheques
      .map((c) => {
        let acts = "";
        if (c.cheque_type === "received") {
          if (c.status === "in_safe")
            acts = `<button class="btn sm" data-act="deposit" data-id="${c.id}">خواباندن</button>
                    <button class="btn sm ghost" data-act="transfer" data-id="${c.id}">واگذاری</button>`;
          else if (c.status === "deposited_to_bank")
            acts = `<button class="btn sm info" data-act="clear" data-id="${c.id}">پاس</button>
                    <button class="btn sm danger" data-act="bounce" data-id="${c.id}">برگشت</button>`;
        } else if (c.cheque_type === "issued" && c.status === "issued") {
          acts = `<button class="btn sm info" data-act="clear" data-id="${c.id}">پاس</button>
                  <button class="btn sm danger" data-act="cancel" data-id="${c.id}">ابطال</button>`;
        }
        return `<tr>
          <td>${esc(c.cheque_number)}</td>
          <td class="num">${toFa(c.sayyad_id || "")}</td>
          <td>${esc(c.party_title || "—")}</td>
          <td>${c.cheque_type === "received" ? "دریافتی" : "صادره"}</td>
          <td>${badge(c.status, CHEQUE_LABEL)}</td>
          <td>${toFa(c.due_date)}</td>
          <td class="num">${money(c.amount)}</td>
          <td class="actions">${acts || "—"}</td>
        </tr>`;
      })
      .join("") || `<tr><td colspan="8" class="empty">چکی ثبت نشده است.</td></tr>`;

  $$("#chequesBody [data-act]").forEach((b) => (b.onclick = () => chequeAction(b.dataset.act, b.dataset.id)));

  const txs = await api(`/tenants/${state.tenant}/treasury/transactions`);
  $("#txBody").innerHTML =
    txs
      .map(
        (t) => `<tr><td>${toFa(t.tx_date)}</td><td>${t.tx_type === "receipt" ? "دریافت" : "پرداخت"}</td>
        <td>${esc(t.method)}</td><td class="num">${money(t.amount)}</td><td>${esc(t.description || "")}</td></tr>`
      )
      .join("") || `<tr><td colspan="5" class="empty">تراکنشی ثبت نشده است.</td></tr>`;
}

async function chequeAction(act, id) {
  const date = todayISO();
  try {
    if (act === "deposit") {
      if (!state.bankAccounts.length) await loadShared();
      if (!state.bankAccounts.length) throw new Error("ابتدا یک حساب بانکی تفصیلی تعریف کنید.");
      await api(`/tenants/${state.tenant}/treasury/cheques/${id}/deposit`, {
        method: "POST",
        body: { bank_account_detail_id: state.bankAccounts[0].id, deposit_date: date },
      });
    } else if (act === "clear") {
      await api(`/tenants/${state.tenant}/treasury/cheques/${id}/clear`, { method: "POST", body: { clear_date: date } });
    } else if (act === "bounce") {
      const reason = prompt("علت برگشت چک؟", "موجودی ناکافی") || "";
      await api(`/tenants/${state.tenant}/treasury/cheques/${id}/bounce`, { method: "POST", body: { date, reason } });
    } else if (act === "cancel") {
      await api(`/tenants/${state.tenant}/treasury/cheques/${id}/cancel`, { method: "POST", body: { date } });
    } else if (act === "transfer") {
      if (!state.customers.length) await loadShared();
      const target = state.customers.find((c) => c.id);
      await api(`/tenants/${state.tenant}/treasury/cheques/${id}/transfer`, {
        method: "POST",
        body: { payee_detail_id: target.id, transfer_date: date },
      });
    }
    toast("عملیات چک با موفقیت انجام شد.");
    loadTreasury();
  } catch (e) { toast(e.message, "error"); }
}

async function receiveCheque() {
  try {
    const body = {
      fiscal_year_id: state.fy,
      customer_detail_id: $("#chCustomer").value,
      sayyad_id: $("#chSayyad").value,
      cheque_number: $("#chNumber").value,
      bank_name: $("#chBank").value,
      due_date: $("#chDue").value,
      amount: Number($("#chAmount").value),
      receive_date: $("#chRecv").value,
    };
    if (!body.customer_detail_id) throw new Error("مشتری را انتخاب کنید.");
    await api(`/tenants/${state.tenant}/treasury/cheques/receive`, { method: "POST", body });
    toast("چک دریافتی ثبت شد (اسناد در صندوق / بدهکاران).");
    loadTreasury();
  } catch (e) { toast(e.message, "error"); }
}

async function issueCheque() {
  try {
    const body = {
      fiscal_year_id: state.fy,
      payee_detail_id: $("#isPayee").value,
      bank_account_detail_id: $("#isBankAcc").value,
      sayyad_id: $("#isSayyad").value,
      cheque_number: $("#isNumber").value,
      bank_name: $("#isBank").value,
      due_date: $("#isDue").value,
      amount: Number($("#isAmount").value),
      issue_date: $("#isDate").value,
    };
    if (!body.payee_detail_id || !body.bank_account_detail_id) throw new Error("ذینفع و حساب بانکی را انتخاب کنید.");
    await api(`/tenants/${state.tenant}/treasury/cheques/issue`, { method: "POST", body });
    toast("چک صادره ثبت شد (بستانکاران / اسناد پرداختنی).");
    loadTreasury();
  } catch (e) { toast(e.message, "error"); }
}

async function recordTreasuryTx() {
  try {
    const body = {
      fiscal_year_id: state.fy,
      tx_type: $("#txType").value,
      method: $("#txMethod").value,
      amount: Number($("#txAmount").value),
      tx_date: $("#txDate").value || todayISO(),
      party_detail_id: $("#txParty").value || null,
      bank_account_detail_id: $("#txBank").value || null,
      description: $("#txDesc").value || null,
    };
    if (!(body.amount > 0)) throw new Error("مبلغ را وارد کنید.");
    const r = await api(`/tenants/${state.tenant}/treasury/transactions`, {
      method: "POST",
      body,
    });
    toast(
      (body.tx_type === "receipt" ? "سند رسید" : "سند پرداخت") +
        " خزانه ثبت شد (سند دوبل صادر گردید)."
    );
    loadTreasury();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function calcRas() {
  const amounts = $$(".rasAmt").map((i) => Number(i.value || 0));
  const dates = $$(".rasDate").map((i) => i.value);
  const cheques = amounts
    .map((a, i) => ({ amount: a, due_date: dates[i] }))
    .filter((c) => c.amount > 0 && c.due_date);
  try {
    const r = await api(`/tenants/${state.tenant}/treasury/ras`, {
      method: "POST",
      body: { base_date: $("#rasBase").value, cheques },
    });
    $("#rasResult").innerHTML = `<div class="totals">
      <div class="t"><span>جمع مبلغ</span><strong>${money(r.total_amount)}</strong></div>
      <div class="t"><span>میانگین وزنی (روز)</span><strong>${toFa(r.weighted_average_days)}</strong></div>
      <div class="t"><span>تاریخ راس</span><strong>${toFa(r.ras_due_date)}</strong></div>
    </div>`;
  } catch (e) { toast(e.message, "error"); }
}

/* ---------------- 4. Inventory ---------------- */
async function loadInventory() {
  if (!state.products.length) await loadShared();
  const [products, warehouses, summary] = await Promise.all([
    api(`/tenants/${state.tenant}/inventory/products`),
    api(`/tenants/${state.tenant}/inventory/warehouses`),
    api(`/tenants/${state.tenant}/inventory/summary`),
  ]);
  state.products = products;
  state.warehouses = warehouses;

  $("#invKpis").innerHTML = `
    <div class="card kpi"><div class="label">تعداد کالاها</div><div class="value">${toFa(summary.sku_count)}</div></div>
    <div class="card kpi alt"><div class="label">ارزش موجودی انبار</div><div class="value">${money(summary.inventory_value)} <span class="unit">تومان</span></div></div>
    <div class="card kpi red"><div class="label">کالاهای زیر حد هشدار</div><div class="value">${toFa(summary.low_stock_count)}</div></div>`;

  const prodOpts = products
    .map((p) => `<option value="${p.id}">${esc(p.title)} (${toFa(p.sku)})</option>`)
    .join("");
  ["#rcProduct", "#dlProduct", "#kardexProduct"].forEach((s) => ($(s).innerHTML = prodOpts));
  fillSelect("#rcWarehouse", warehouses, "id", "title");
  fillSelect("#dlWarehouse", warehouses, "id", "title");
  fillSelect("#rcSupplier", state.suppliers, "id", "title", "تأمین‌کننده");

  $("#productsBody").innerHTML =
    products
      .map(
        (p) => `<tr>
          <td>${toFa(p.sku)}</td><td>${esc(p.title)}</td><td>${esc(p.category || "—")}</td>
          <td class="num">${toFa(p.current_stock)}</td>
          <td class="num">${money(p.weighted_avg_cost)}</td>
          <td class="num">${money(p.current_stock * p.weighted_avg_cost)}</td>
          <td class="num">${toFa(p.min_stock_alert)}</td>
        </tr>`
      )
      .join("") || `<tr><td colspan="7" class="empty">کالایی تعریف نشده است.</td></tr>`;
}

async function doReceipt() {
  try {
    const r = await api(`/tenants/${state.tenant}/inventory/receipts`, {
      method: "POST",
      body: {
        fiscal_year_id: state.fy,
        warehouse_id: $("#rcWarehouse").value,
        product_id: $("#rcProduct").value,
        supplier_detail_id: $("#rcSupplier").value,
        quantity: Number($("#rcQty").value),
        unit_cost: Number($("#rcCost").value),
        tx_date: $("#rcDate").value,
      },
    });
    toast(`رسید انبار ثبت شد. موجودی: ${toFa(r.new_stock)} | میانگین: ${money(r.new_avg_cost)}`);
    loadInventory();
  } catch (e) { toast(e.message, "error"); }
}

async function doDelivery() {
  try {
    const r = await api(`/tenants/${state.tenant}/inventory/deliveries`, {
      method: "POST",
      body: {
        fiscal_year_id: state.fy,
        warehouse_id: $("#dlWarehouse").value,
        product_id: $("#dlProduct").value,
        quantity: Number($("#dlQty").value),
        tx_date: $("#dlDate").value,
      },
    });
    toast(`حواله ثبت شد. بهای تمام شده: ${money(r.total_cogs)} | موجودی: ${toFa(r.remaining_stock)}`);
    loadInventory();
  } catch (e) { toast(e.message, "error"); }
}

async function doSalesReturn() {
  try {
    const r = await api(`/tenants/${state.tenant}/inventory/sales-returns`, {
      method: "POST",
      body: {
        fiscal_year_id: state.fy,
        warehouse_id: $("#dlWarehouse").value,
        product_id: $("#dlProduct").value,
        quantity: 1,
        tx_date: todayISO(),
      },
    });
    toast(`برگشت فروش ثبت شد. موجودی: ${toFa(r.new_stock)}`);
    loadInventory();
  } catch (e) { toast(e.message, "error"); }
}

async function doReconciliation() {
  try {
    const count = prompt("تعداد شمارش‌شده را وارد کنید:", "0");
    if (count === null) return;
    const r = await api(`/tenants/${state.tenant}/inventory/reconciliation`, {
      method: "POST",
      body: {
        fiscal_year_id: state.fy,
        warehouse_id: $("#dlWarehouse").value,
        product_id: $("#dlProduct").value,
        counted_quantity: Number(count),
        tx_date: todayISO(),
      },
    });
    toast(`مغایرت ثبت شد. موجودی جدید: ${toFa(r.new_stock)}`);
    loadInventory();
  } catch (e) { toast(e.message, "error"); }
}

async function loadKardex() {
  try {
    const pid = $("#kardexProduct").value;
    if (!pid) return;
    const rows = await api(`/tenants/${state.tenant}/inventory/kardex/${pid}`);
    $("#kardexBody").innerHTML =
      rows
        .map(
          (k) => `<tr>
            <td>${toFa(k.tx_number)}</td><td>${toFa(k.date)}</td><td>${esc(k.tx_type_label || k.tx_type)}</td>
            <td class="num">${toFa(k.quantity)}</td>
            <td class="num">${money(k.unit_cost)}</td>
            <td class="num">${money(k.total_cost)}</td>
            <td class="num">${toFa(k.running_qty)}</td>
            <td class="num">${money(k.running_avg_cost)}</td>
          </tr>`
        )
        .join("") || `<tr><td colspan="8" class="empty">ترددی ثبت نشده است.</td></tr>`;
  } catch (e) { toast(e.message, "error"); }
}

/* ---------------- 5. Sales / Invoicing ---------------- */
function invRow(item) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input class="ivTitle" value="${esc(item ? item.title : "")}" placeholder="شرح کالا/خدمت"></td>
    <td><input type="number" class="ivQty num" value="${item ? item.qty : 1}" step="1" min="1"></td>
    <td><input type="number" class="ivPrice num" value="${item ? item.price : 0}"></td>
    <td><input type="number" class="ivDisc num" value="${item ? item.disc : 0}"></td>
    <td class="num ivVat">۰</td>
    <td class="num ivTotal">۰</td>
    <td><button class="btn sm danger ivDel">×</button></td>`;
  tr.querySelector(".ivDel").onclick = () => { tr.remove(); updateInvoiceTotals(); };
  tr.querySelectorAll("input").forEach((i) => (i.oninput = updateInvoiceTotals));
  $("#invRows tbody").appendChild(tr);
  updateInvoiceTotals();
  return tr;
}

function readInvoiceRows() {
  return $$("#invRows tbody tr").map((tr) => {
    const qty = Number(tr.querySelector(".ivQty").value || 0);
    const price = Number(tr.querySelector(".ivPrice").value || 0);
    const disc = Number(tr.querySelector(".ivDisc").value || 0);
    const net = qty * price - disc;
    const vat = Math.round(net * 0.1);
    return {
      tr,
      title: tr.querySelector(".ivTitle").value,
      qty, price, disc, net, vat, total: net + vat,
    };
  });
}

function updateInvoiceTotals() {
  const rows = readInvoiceRows();
  let gross = 0, disc = 0, vat = 0, payable = 0;
  rows.forEach((r) => {
    gross += r.qty * r.price;
    disc += r.disc;
    vat += r.vat;
    payable += r.total;
    r.tr.querySelector(".ivVat").textContent = money(r.vat);
    r.tr.querySelector(".ivTotal").textContent = money(r.total);
  });
  $("#invTotals").innerHTML = `
    <div class="t"><span>جمع ناخالص</span><strong>${money(gross)}</strong></div>
    <div class="t"><span>تخفیف</span><strong>${money(disc)}</strong></div>
    <div class="t"><span>مالیات بر ارزش افزوده ۱۰٪</span><strong>${money(vat)}</strong></div>
    <div class="t"><span>قابل پرداخت</span><strong>${money(payable)}</strong></div>`;
}

async function loadSales() {
  if (!state.customers.length) await loadShared();
  fillSelect("#invCustomer", state.customers, "id", "title", "انتخاب مشتری");
  if (!state.products.length) {
    state.products = await api(`/tenants/${state.tenant}/inventory/products`);
  }
  $("#invProduct").innerHTML = state.products
    .map(
      (p) =>
        `<option value="${p.id}" data-price="${p.sale_price || 0}">${esc(p.title)} — ${money(
          p.sale_price || 0
        )} تومان</option>`
    )
    .join("");
  if (!$("#invRows tbody").children.length) { invRow(); invRow(); }
  updateInvoiceTotals();

  const invoices = await api(`/tenants/${state.tenant}/invoices`);
  $("#invoicesBody").innerHTML =
    invoices
      .map(
        (i) => `<tr>
          <td>${toFa(i.number)}</td>
          <td>${toFa(i.date)}</td>
          <td>${toFa(i.date_jalali || "")}</td>
          <td>${esc(i.customer || "—")}</td>
          <td>${esc(i.invoice_type_label || i.invoice_type)}</td>
          <td>${esc(i.payment_status_label || i.payment_status)}</td>
          <td class="num">${money(i.final_payable)}</td>
          <td class="num">${toFa(i.tax_id || "")}</td>
          <td>${badge(i.raw_status, STATUS_LABEL)}</td>
          <td class="actions">
            <button class="btn sm ghost" data-view-inv="${i.id}">نمایش</button>
            <button class="btn sm ghost" data-docflow-inv="${i.id}" title="ارتباط و پیگیری اسناد">🔗 ارتباط اسناد</button>
            ${i.raw_status === "draft" ? `<button class="btn sm info" data-conf="${i.id}">تایید و ثبت سند</button>` : ""}
            ${i.raw_status === "confirmed" ? `<button class="btn sm danger" data-cancel="${i.id}">ابطال</button>` : ""}
          </td>
        </tr>`
      )
      .join("") || `<tr><td colspan="10" class="empty">فاکتوری صادر نشده است.</td></tr>`;

  $$("#invoicesBody [data-conf]").forEach((b) => (b.onclick = () => confirmInvoice(b.dataset.conf)));
  $$("#invoicesBody [data-cancel]").forEach((b) => (b.onclick = () => cancelInvoice(b.dataset.cancel)));
  $$("#invoicesBody [data-view-inv]").forEach((b) => (b.onclick = () => showInvoice(b.dataset.viewInv)));
  $$("#invoicesBody [data-docflow-inv]").forEach((b) => (b.onclick = () => openDocFlow("invoice", b.dataset.docflowInv)));
}

async function createInvoice() {
  try {
    const rows = readInvoiceRows().filter((r) => r.title && r.qty > 0);
    if (!rows.length) throw new Error("حداقل یک ردیف کالا وارد کنید.");
    const customer = $("#invCustomer").value;
    if (!customer) throw new Error("مشتری را انتخاب کنید.");
    const created = await api(`/tenants/${state.tenant}/invoices`, {
      method: "POST",
      body: {
        fiscal_year_id: state.fy,
        customer_detail_id: customer,
        invoice_date: $("#invDate").value,
        invoice_type: $("#invType").value,
        payment_status: $("#invPay").value,
        items: rows.map((r, i) => ({
          item_code: "2720000" + String(100000 + i).slice(-6),
          item_title: r.title,
          unit: "تعداد",
          quantity: r.qty,
          unit_price: r.price,
          discount: r.disc,
          vat_rate: 0.1,
        })),
      },
    });
    toast(`فاکتور شماره ${toFa(created.invoice_number)} ثبت شد.`);
    await showInvoice(created.invoice_id);
    loadSales();
  } catch (e) { toast(e.message, "error"); }
}

async function confirmInvoice(id) {
  try {
    await api(`/tenants/${state.tenant}/invoices/${id}/confirm`, { method: "POST", body: {} });
    toast("فاکتور تایید و سند حسابداری خودکار صادر شد.");
    await showInvoice(id);
    loadSales();
  } catch (e) { toast(e.message, "error"); }
}

async function cancelInvoice(id) {
  if (!confirm("فاکتور ابطال و سند معکوس صادر شود؟")) return;
  try {
    await api(`/tenants/${state.tenant}/invoices/${id}/cancel`, { method: "POST", body: {} });
    toast("فاکتور ابطال و سند استورنو صادر شد.");
    loadSales();
  } catch (e) { toast(e.message, "error"); }
}

async function showInvoice(id) {
  try {
    const inv = await api(`/tenants/${state.tenant}/invoices/${id}`);
    state.lastInvoice = inv;
    const rows = inv.items
      .map(
        (it) => `<tr>
          <td>${esc(it.item_title)}</td>
          <td class="num">${toFa(it.quantity)}</td>
          <td class="num">${money(it.unit_price)}</td>
          <td class="num">${money(it.discount)}</td>
          <td class="num">${money(it.vat_amount)}</td>
          <td class="num">${money(it.total_price)}</td>
        </tr>`
      )
      .join("");
    $("#invoicePreview").className = "";
    $("#invoicePreview").innerHTML = `
      <div class="invoice-sheet">
        <header>
          <div><h2>فاکتور فروش کالا و خدمات</h2>
            <div class="muted">شماره: ${toFa(inv.invoice_number)} — تاریخ: ${toFa(inv.date_jalali || inv.invoice_date)}</div>
            <div class="muted">مشتری: ${esc(inv.customer_name || "—")}</div>
          </div>
          <div style="text-align:left;">
            <div class="taxid">${esc(inv.tax_unique_id)}</div>
            <div class="muted" style="font-size:11px;">شناسه یکتای مالیاتی (Verhoeff: ${inv.tax_id_valid ? "معتبر ✔" : "نامعتبر ✖"})</div>
            <div class="muted" style="font-size:11px;">${esc(inv.invoice_type_label)} — ${esc(inv.payment_status_label)}</div>
          </div>
        </header>
        <table>
          <thead><tr><th>شرح</th><th class="num">تعداد</th><th class="num">قیمت واحد</th><th class="num">تخفیف</th><th class="num">مالیات</th><th class="num">جمع</th></tr></thead>
          <tbody>${rows}</tbody>
          <tfoot>
            <tr><td colspan="2">جمع کل</td><td colspan="2"></td><td class="num">${money(inv.total_vat)}</td><td class="num">${money(inv.final_payable)}</td></tr>
          </tfoot>
        </table>
        <div class="totals" style="margin-top:10px;">
          <div class="t"><span>ناخالص</span><strong>${money(inv.total_amount)}</strong></div>
          <div class="t"><span>تخفیف</span><strong>${money(inv.total_discount)}</strong></div>
          <div class="t"><span>ارزش افزوده</span><strong>${money(inv.total_vat)}</strong></div>
          <div class="t"><span>قابل پرداخت</span><strong>${money(inv.final_payable)}</strong></div>
        </div>
        <div class="actions" style="margin-top:12px;">
          <button class="btn sm" id="btnPrintInvoice">چاپ / خروجی PDF</button>
        </div>
      </div>`;
    $("#btnPrintInvoice").onclick = printInvoice;
  } catch (e) { toast(e.message, "error"); }
}

function printInvoice() {
  const node = $("#invoicePreview .invoice-sheet");
  if (!node) return;
  $("#printArea").innerHTML = node.outerHTML;
  window.print();
}

/* ---------------- 6. Payroll ---------------- */
async function loadPayroll() {
  const employees = await api(`/tenants/${state.tenant}/payroll/employees`);
  state.employees = employees;

  $("#employeesBody").innerHTML =
    employees
      .map(
        (e) => `<tr>
          <td>${toFa(e.sub_ledger_code || "—")}</td>
          <td>${esc(e.full_name)}</td>
          <td>${esc(e.job_title)}</td>
          <td class="num">${money(e.base_monthly_salary)}</td>
          <td class="num">${money(e.housing_allowance)}</td>
          <td class="num">${money(e.grocery_allowance)}</td>
          <td class="num">${toFa(e.bank_shaba || "—")}</td>
        </tr>`
      )
      .join("") || `<tr><td colspan="7" class="empty">پرسنلی ثبت نشده است.</td></tr>`;

  $("#prEmployees").innerHTML =
    employees
      .map(
        (e) => `<tr>
          <td><input type="checkbox" class="prSel" value="${e.id}" checked style="width:auto;"></td>
          <td>${esc(e.full_name)}</td>
          <td><input type="number" class="prDays num" value="30" data-emp="${e.id}"></td>
          <td><input type="number" class="prOt num" value="0" data-emp="${e.id}"></td>
        </tr>`
      )
      .join("") || `<tr><td colspan="4" class="empty">پرسنلی ثبت نشده است.</td></tr>`;

  if (state.lastRun) await showPayslips(state.lastRun);

  try {
    const brackets = await api(`/tenants/${state.tenant}/payroll/tax-brackets`);
    $("#taxBracketsBody").innerHTML = brackets
      .map(
        (b) => `<tr>
          <td class="num">${money(b.from)}</td>
          <td class="num">${b.to == null ? "و بالاتر" : money(b.to)}</td>
          <td class="num">${toFa(Math.round(b.rate * 100))}٪</td>
        </tr>`
      )
      .join("");
  } catch (e) {
    $("#taxBracketsBody").innerHTML = `<tr><td colspan="3" class="empty">جدول بارگذاری نشد.</td></tr>`;
  }
}

async function addEmployee() {
  try {
    await api(`/tenants/${state.tenant}/payroll/employees`, {
      method: "POST",
      body: {
        national_id: $("#empNational").value.trim(),
        full_name: $("#empName").value.trim(),
        job_title: $("#empJob").value,
        base_monthly_salary: Number($("#empBase").value),
        housing_allowance: Number($("#empHousing").value),
        grocery_allowance: Number($("#empGrocery").value),
        child_count: Number($("#empChildren").value || 0),
        bank_shaba: $("#empShaba").value || null,
      },
    });
    toast("پرسنل با موفقیت ثبت شد (تفصیلی شناور ایجاد گردید).");
    loadPayroll();
  } catch (e) { toast(e.message, "error"); }
}

async function runPayroll() {
  try {
    const ids = $$("#prEmployees .prSel").filter((c) => c.checked).map((c) => c.value);
    if (!ids.length) throw new Error("حداقل یک پرسنل را انتخاب کنید.");
    const records = ids.map((id) => ({
      employee_id: id,
      worked_days: Number($(`#prEmployees .prDays[data-emp="${id}"]`).value || 30),
      overtime_hours: Number($(`#prEmployees .prOt[data-emp="${id}"]`).value || 0),
    }));
    const res = await api(`/tenants/${state.tenant}/payroll/process`, {
      method: "POST",
      body: {
        fiscal_year_id: state.fy,
        month_label: $("#prMonth").value,
        run_date: $("#prDate").value,
        records,
      },
    });
    state.lastRun = res.payroll_run_id;
    state.lastRunLabel = $("#prMonth").value;
    $("#payrollResult").innerHTML = `<div class="totals">
      <div class="t"><span>مجموع ناخالص</span><strong>${money(res.total_gross)}</strong></div>
      <div class="t"><span>بیمه ۳۰٪</span><strong>${money(res.total_insurance_30pct)}</strong></div>
      <div class="t"><span>مالیات ماده ۸۴</span><strong>${money(res.total_tax)}</strong></div>
      <div class="t"><span>خالص پرداختی</span><strong>${money(res.total_net_payable)}</strong></div>
    </div>`;
    toast("لیست حقوق محاسبه و سند دوبل صادر شد.");
    await showPayslips(res.payroll_run_id);
  } catch (e) { toast(e.message, "error"); }
}

async function showPayslips(runId) {
  try {
    const slips = await api(`/tenants/${state.tenant}/payroll/runs/${runId}/payslips`);
    $("#payslipsBody").innerHTML =
      slips
        .map(
          (s, i) => `<tr>
            <td>${esc(s.full_name)}</td>
            <td class="num">${money(s.gross_salary)}</td>
            <td class="num">${money(s.employee_insurance)}</td>
            <td class="num">${money(s.employer_insurance)}</td>
            <td class="num">${money(s.income_tax)}</td>
            <td class="num">${money(s.net_payable)}</td>
            <td><button class="btn sm ghost" data-slip="${i}">فیش</button></td>
          </tr>`
        )
        .join("") || `<tr><td colspan="7" class="empty">فیشی صادر نشده است.</td></tr>`;
    $$("#payslipsBody [data-slip]").forEach(
      (b) => (b.onclick = () => showPayslipModal(slips[Number(b.dataset.slip)]))
    );
    const sum = (k) => slips.reduce((a, s) => a + Number(s[k] || 0), 0);
    $("#payrollTotals").innerHTML = `
      <div class="t"><span>ناخالص</span><strong>${money(sum("gross_salary"))}</strong></div>
      <div class="t"><span>بیمه کارمند</span><strong>${money(sum("employee_insurance"))}</strong></div>
      <div class="t"><span>بیمه کارفرما</span><strong>${money(sum("employer_insurance"))}</strong></div>
      <div class="t"><span>مالیات</span><strong>${money(sum("income_tax"))}</strong></div>
      <div class="t"><span>قابل پرداخت</span><strong>${money(sum("net_payable"))}</strong></div>`;
  } catch (e) { toast(e.message, "error"); }
}

/* ---------------- bootstrap & wiring ---------------- */
async function bootstrap(silent) {
  try {
    const r = await api("/bootstrap", { method: "POST", body: {} });
    state.tenant = r.tenant_id || state.tenant;
    state.fy = r.fiscal_year_id || state.fy;
    $("#fyChip").textContent = "سال مالی ۱۴۰۵ — " + toFa(state.tenant);
    $("#sysInfo").innerHTML = `آربین نسخه ۲.۰<br>شرکت: ${toFa(state.tenant)}<br>سال مالی: ${toFa(state.fy)}`;
    await loadShared();
    if (!silent) toast("سیستم راه‌اندازی شد (کدینگ استاندارد + داده نمایشی).");
    return true;
  } catch (e) {
    $("#sysInfo").textContent = "خطا در راه‌اندازی";
    if (!silent) toast(e.message, "error");
    return false;
  }
}

function setDefaultDates() {
  const t = todayISO();
  ["#jeDate", "#chRecv", "#rcDate", "#dlDate", "#invDate", "#prDate", "#isDate"].forEach((s) => {
    const el = $(s);
    if (el && !el.value) el.value = t;
  });
  $("#chDue").value = "2026-06-20";
  $("#isDue").value = "2026-08-20";
}

function wire() {
  $$("#nav button").forEach((b) => (b.onclick = () => go(b.dataset.view)));
  $("#btnRefresh").onclick = refresh;
  $("#btnBootstrap").onclick = () => bootstrap(false);
  $("#modalClose").onclick = closeModal;
  $("#modalOverlay").onclick = (e) => {
    if (e.target === $("#modalOverlay")) closeModal();
  };
  
  // Standard ERP Hotkeys & Escape
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (lookupState && lookupState.active) {
        e.preventDefault();
        closeLookup();
      } else {
        closeModal();
      }
    } else if (e.key === "F2") {
      e.preventDefault();
      go("ledger");
      $("#jeRows tbody").innerHTML = "";
      jeRow(); jeRow();
      $("#jeDesc").focus();
      toast("فرم صدور سند حسابداری باز شد (F2)");
    } else if (e.key === "F3") {
      if (state.view === "ledger" && (!lookupState || !lookupState.active)) {
        e.preventDefault();
        const active = document.activeElement;
        const tr = active ? active.closest("tr") : null;
        if (tr && active.classList.contains("jeDetail")) {
          const btnDet = tr.querySelector(".btnLookupDetail");
          if (btnDet) btnDet.click();
        } else if (tr) {
          const btnAcc = tr.querySelector(".btnLookupAcc");
          if (btnAcc) btnAcc.click();
        } else {
          openLookup("account", (acc) => {
            const firstRow = $("#jeRows tbody tr");
            if (firstRow) {
              const codeInp = firstRow.querySelector(".jeAccCode");
              const accSel = firstRow.querySelector(".jeAcc");
              if (codeInp) codeInp.value = acc.code;
              if (accSel) accSel.value = acc.code;
            }
          });
        }
      }
    } else if (e.key === "F4") {
      e.preventDefault();
      if (state.view === "ledger") $("#jeSave").click();
    } else if (e.key === "F6") {
      e.preventDefault();
      go("drilldown");
      toast("سیستم مرور حساب‌ها باز شد (F6)");
    } else if (e.key === "F8") {
      e.preventDefault();
      go("docflow");
      toast("سیستم پیگیری و ارتباط اسناد باز شد (F8)");
    }
  });

  // Top Ribbon Bar
  const ribNew = $("#ribbonNewJe");
  if (ribNew) ribNew.onclick = () => {
    go("ledger");
    $("#jeRows tbody").innerHTML = "";
    jeRow(); jeRow();
    $("#jeDesc").focus();
  };
  const ribSave = $("#ribbonSaveJe");
  if (ribSave) ribSave.onclick = () => $("#jeSave").click();
  const ribDd = $("#ribbonDrillDown");
  if (ribDd) ribDd.onclick = () => {
    go("drilldown");
    state.drilldown.level = "group";
    loadDrillDown();
  };
  const ribTb = $("#ribbonTrialBalance");
  if (ribTb) ribTb.onclick = () => {
    go("ledger");
    $("#tbLevel").scrollIntoView({ behavior: "smooth" });
  };
  const ribDf = $("#ribbonDocFlow");
  if (ribDf) ribDf.onclick = () => go("docflow");
  const ribInv = $("#ribbonNewInvoice");
  if (ribInv) ribInv.onclick = () => go("sales");
  const ribChq = $("#ribbonNewCheque");
  if (ribChq) ribChq.onclick = () => go("treasury");

  // Reset drilldown button
  const ddReset = $("#ddResetBtn");
  if (ddReset) ddReset.onclick = () => {
    state.drilldown = { level: "group", groupCode: null, groupTitle: null, generalCode: null, generalTitle: null, subsidiaryCode: null, subsidiaryTitle: null };
    loadDrillDown();
  };

  // Document Flow Controls
  const dfRecent = $("#dfRecentSelect");
  if (dfRecent) {
    dfRecent.onchange = (e) => {
      const val = e.target.value;
      if (val) {
        const [type, id] = val.split(":");
        state.activeDocFlow = { entityType: type, entityId: id };
        loadDocumentFlow();
      }
    };
  }
  const dfRef = $("#dfRefreshBtn");
  if (dfRef) dfRef.onclick = () => loadDocumentFlow();

  // ledger
  $("#jeAddRow").onclick = jeRow;
  $("#jeSave").onclick = async () => {
    try {
      const rows = $$("#jeRows tbody tr").map((tr) => ({
        account_code: tr.querySelector(".jeAcc").value,
        sub_ledger_code: tr.querySelector(".jeDetail") ? tr.querySelector(".jeDetail").value || undefined : undefined,
        description: tr.querySelector(".jeDesc").value || $("#jeDesc").value,
        debit: parseFormattedNumber(tr.querySelector(".jeDr").value || 0),
        credit: parseFormattedNumber(tr.querySelector(".jeCr").value || 0),
      })).filter((r) => r.debit > 0 || r.credit > 0);
      if (rows.length < 2) throw new Error("سند باید حداقل دو ردیف (بدهکار و بستانکار) داشته باشد.");
      await api(`/tenants/${state.tenant}/entries`, {
        method: "POST",
        body: {
          fiscal_year_id: state.fy,
          entry_date: $("#jeDate").value,
          description: $("#jeDesc").value || "سند دستی",
          status: $("#jeStatus").value,
          items: rows,
        },
      });
      toast("سند حسابداری با تراز دوبل ثبت شد.");
      $("#jeDesc").value = "";
      $$("#jeRows tbody").forEach((b) => (b.innerHTML = ""));
      jeRow(); jeRow();
      loadLedger();
    } catch (e) { toast(e.message, "error"); }
  };
  $("#tbLevel").onchange = loadTrialBalance;
  $("#jeDrafts").onchange = loadLedger;
  $("#asRun").onclick = runAccountStatement;
  $("#btnCloseFY").onclick = closeFY;
  $("#btnOpenFY").onclick = openFY;

  // treasury
  $("#btnReceiveCheque").onclick = receiveCheque;
  $("#btnIssueCheque").onclick = issueCheque;
  $("#btnTxSave").onclick = recordTreasuryTx;
  $("#chequeFilter").onchange = loadTreasury;
  $("#btnRas").onclick = calcRas;

  // inventory
  $("#btnReceipt").onclick = doReceipt;
  $("#btnDelivery").onclick = doDelivery;
  $("#btnSalesReturn").onclick = doSalesReturn;
  $("#btnRecon").onclick = doReconciliation;
  $("#btnKardex").onclick = loadKardex;

  // sales
  $("#invAddRow").onclick = () => invRow();
  $("#invAddProduct").onclick = async () => {
    if (!state.products.length) {
      state.products = await api(`/tenants/${state.tenant}/inventory/products`);
    }
    const sel = $("#invProduct");
    const p = state.products.find((x) => x.id === sel.value) || state.products[0];
    if (!p) return toast("کالایی در انبار تعریف نشده است.", "error");
    invRow({ title: p.title, qty: 1, price: p.sale_price || 0, disc: 0 });
    toast("کالا با قیمت خودکار به فاکتور افزوده شد.");
  };
  $("#btnCreateInvoice").onclick = createInvoice;

  // payroll
  $("#btnAddEmp").onclick = addEmployee;
  $("#btnRunPayroll").onclick = runPayroll;

  // fixed assets
  $("#faSave").onclick = saveFixedAsset;
  $("#faRunDepr").onclick = runFixedAssetDepr;

  // manufacturing
  $("#bomSave").onclick = saveBOM;
  $("#orderCreate").onclick = createProductionOrder;

  // contracting
  $("#cntSave").onclick = saveContract;
  $("#billSubmit").onclick = submitProgressBilling;

  // Interactive Dashboard Workflow Map
  $$(".workflow-step-node[data-flow-target]").forEach((node) => {
    node.onclick = () => {
      const target = node.dataset.flowTarget;
      go(target);
      if (target === "ledger") {
        setTimeout(() => {
          const firstInp = $("#jeRows tbody tr .jeAccCode");
          if (firstInp) firstInp.focus();
        }, 150);
      }
    };
  });
  const btnDashDf = $("#btnDashToDocFlow");
  if (btnDashDf) btnDashDf.onclick = () => go("docflow");

  // Fast Lookup Modal Events
  initLookupEvents();
}

/* ---------------- 7. Fixed Assets (اموال و استهلاک ماده ۱۴۹) ---------------- */
async function loadFixedAssets() {
  const assets = await api(`/tenants/${state.tenant}/fixed-assets`);
  const tbody = $("#faTableBody");
  tbody.innerHTML = "";
  if (!assets.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">هیچ دارایی ثابتی ثبت نشده است.</td></tr>';
    return;
  }
  assets.forEach((a) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${esc(a.asset_code)}</strong></td>
      <td>${esc(a.title)}</td>
      <td>${esc(a.category)}</td>
      <td>${a.depreciation_method === "declining_balance" ? "مانده نزولی" : "خط مستقیم"}</td>
      <td class="num">${money(a.purchase_cost)}</td>
      <td class="num text-danger">${money(a.accumulated_depreciation)}</td>
      <td class="num font-bold text-success">${money(a.book_value)}</td>
      <td><span class="chip ${a.status === 'active' ? 'ok' : 'warn'}">${a.status === 'active' ? 'در حال بهره‌برداری' : 'اسقاط/واگذار شده'}</span></td>
      <td>
        ${a.status === 'active' ? `<button class="btn sm ghost" onclick="disposeAssetPrompt('${esc(a.asset_code)}')">واگذاری / اسقاط</button>` : '—'}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function saveFixedAsset() {
  const code = $("#faCode").value.trim();
  const title = $("#faTitle").value.trim();
  const cost = parseFloat($("#faCost").value || 0);
  const buyDate = $("#faBuyDate").value || todayISO();
  if (!code || !title || cost <= 0) return toast("کد، عنوان و مبلغ خرید دارایی الزامی است.", "error");

  const method = $("#faMethod").value;
  const life = parseInt($("#faLife").value || 5, 10);
  const rate = method === "declining_balance" ? 0.30 : (1.0 / life);

  await api(`/tenants/${state.tenant}/fixed-assets`, {
    method: "POST",
    body: {
      asset_code: code,
      title,
      category: $("#faCategory").value,
      purchase_date: buyDate,
      purchase_cost: cost,
      depreciation_method: method,
      useful_life_years: life,
      depreciation_rate: rate,
      location: $("#faLoc").value.trim() || "دفتر مرکزی",
      post_purchase_voucher: true,
      fiscal_year_id: state.fy?.id,
    }
  });
  toast("دارایی ثابت با موفقیت پلاک‌گذاری و سند خرید آن صادر شد.", "ok");
  $("#faCode").value = "";
  $("#faTitle").value = "";
  $("#faCost").value = "";
  loadFixedAssets();
}

async function runFixedAssetDepr() {
  if (!state.fy) return toast("سال مالی فعال یافت نشد.", "error");
  const pDate = $("#faDeprDate").value || todayISO();
  const months = parseInt($("#faDeprMonths").value || 12, 10);

  const res = await api(`/tenants/${state.tenant}/fixed-assets/depreciation/run`, {
    method: "POST",
    body: {
      fiscal_year_id: state.fy.id,
      period_date: pDate,
      period_name: `استهلاک دوره طبق ماده ۱۴۹ (${months} ماهه)`,
      months,
    }
  });
  toast(`محاسبه استهلاک انجام شد: مبلغ ${money(res.total_depreciation)} تومان سند خورد.`, "ok");
  loadFixedAssets();
}

window.disposeAssetPrompt = async function(assetCode) {
  const price = prompt(`مبلغ فروش دارایی ${assetCode} را وارد کنید (تومان):`, "0");
  if (price === null) return;
  try {
    const res = await api(`/tenants/${state.tenant}/fixed-assets/${assetCode}/dispose`, {
      method: "POST",
      body: {
        fiscal_year_id: state.fy.id,
        disposal_date: todayISO(),
        disposal_type: "sale",
        sale_price: parseFloat(price) || 0,
      }
    });
    toast(`دارایی با موفقیت واگذار شد. سود/زیان: ${money(res.gain_or_loss)} تومان`, "ok");
    loadFixedAssets();
  } catch (e) {
    toast(e.message, "error");
  }
};

/* ---------------- 8. Manufacturing & BOM (سیستم تولید) ---------------- */
async function loadManufacturing() {
  if (!state.products.length) {
    state.products = await api(`/tenants/${state.tenant}/inventory/products`);
  }
  const bomSel = $("#bomProduct");
  bomSel.innerHTML = state.products.map(p => `<option value="${p.id}">${esc(p.title)} (${esc(p.sku)})</option>`).join("");

  const boms = await api(`/tenants/${state.tenant}/manufacturing/boms`);
  const orderBomSel = $("#orderBomSelect");
  orderBomSel.innerHTML = boms.map(b => `<option value="${b.id}">${esc(b.title)} (محصول: ${esc(b.product_title || b.target_product_id)})</option>`).join("");

  const orders = await api(`/tenants/${state.tenant}/manufacturing/orders`);
  const tbody = $("#mfgOrdersBody");
  tbody.innerHTML = "";
  if (!orders.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="muted" style="text-align:center;">هیچ سفارش تولیدی ثبت نشده است.</td></tr>';
    return;
  }
  orders.forEach((o) => {
    const tr = document.createElement("tr");
    let statusText = "در انتظار";
    let statusClass = "muted";
    if (o.status === "in_progress") { statusText = "در خط تولید (WIP)"; statusClass = "warn"; }
    else if (o.status === "completed") { statusText = "تکمیل و رسید انبار"; statusClass = "ok"; }

    let actionBtn = "";
    if (o.status === "draft") {
      actionBtn = `<button class="btn sm" onclick="startOrder('${o.id}')">آغاز ساخت (حواله مواد)</button>`;
    } else if (o.status === "in_progress") {
      actionBtn = `<button class="btn sm ok" onclick="completeOrder('${o.id}')">تکمیل تولید و رسید به انبار</button>`;
    } else {
      actionBtn = `<span class="muted">سند صادر شده</span>`;
    }

    tr.innerHTML = `
      <td><strong>${esc(o.order_no)}</strong></td>
      <td>${esc(o.product_title || o.target_product_id)}</td>
      <td class="num">${toFa(o.planned_qty)}</td>
      <td>${toFa(o.start_date)}</td>
      <td class="num">${money(o.material_cost)}</td>
      <td class="num font-bold">${money(o.unit_cost)}</td>
      <td><span class="chip ${statusClass}">${statusText}</span></td>
      <td>${actionBtn}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function saveBOM() {
  const prodId = $("#bomProduct").value;
  const title = $("#bomTitle").value.trim();
  const labor = parseFloat($("#bomLabor").value || 0);
  const ovh = parseFloat($("#bomOvh").value || 0);
  if (!prodId || !title) return toast("انتخاب محصول و عنوان فرمول الزامی است.", "error");

  const rawItems = state.products.filter(p => p.id !== prodId).slice(0, 2).map(p => ({
    raw_material_id: p.id,
    qty_required: 1.0,
    waste_percentage: 2.0
  }));

  if (!rawItems.length) return toast("حداقل یک ماده اولیه در لیست کالاها باید تعریف شده باشد.", "error");

  await api(`/tenants/${state.tenant}/manufacturing/boms`, {
    method: "POST",
    body: {
      target_product_id: prodId,
      title,
      standard_qty: 1.0,
      direct_labor_rate: labor,
      overhead_rate: ovh,
      items: rawItems
    }
  });
  toast("فرمول ساخت استاندارد (BOM) با موفقیت ثبت شد.", "ok");
  $("#bomTitle").value = "";
  loadManufacturing();
}

async function createProductionOrder() {
  const bomId = $("#orderBomSelect").value;
  const no = $("#orderNo").value.trim();
  const qty = parseFloat($("#orderQty").value || 0);
  const sDate = $("#orderStartDate").value || todayISO();
  if (!bomId || !no || qty <= 0) return toast("انتخاب فرمول، شماره سفارش و تعداد معتبر الزامی است.", "error");

  await api(`/tenants/${state.tenant}/manufacturing/orders`, {
    method: "POST",
    body: {
      bom_id: bomId,
      order_no: no,
      planned_qty: qty,
      start_date: sDate
    }
  });
  toast("سفارش تولید صادر شد.", "ok");
  $("#orderNo").value = "";
  loadManufacturing();
}

window.startOrder = async function(orderId) {
  if (!state.warehouses?.length) {
    state.warehouses = await api(`/tenants/${state.tenant}/inventory/warehouses`);
  }
  const whId = state.warehouses[0]?.id;
  if (!whId) return toast("انباری در سیستم تعریف نشده است.", "error");

  try {
    const res = await api(`/tenants/${state.tenant}/manufacturing/orders/${orderId}/start`, {
      method: "POST",
      body: {
        fiscal_year_id: state.fy.id,
        warehouse_id: whId,
        issue_date: todayISO(),
      }
    });
    toast(`تولید آغاز و مواد اولیه به ارزش ${money(res.total_material_cost)} تومان به خط مصرف حواله شد.`, "ok");
    loadManufacturing();
  } catch (e) {
    toast(e.message, "error");
  }
};

window.completeOrder = async function(orderId) {
  const whId = state.warehouses[0]?.id;
  try {
    const res = await api(`/tenants/${state.tenant}/manufacturing/orders/${orderId}/complete`, {
      method: "POST",
      body: {
        fiscal_year_id: state.fy.id,
        warehouse_id: whId,
        completion_date: todayISO(),
      }
    });
    toast(`سفارش تولید تکمیل شد! بهای تمام شده هر واحد: ${money(res.unit_cost)} تومان`, "ok");
    loadManufacturing();
  } catch (e) {
    toast(e.message, "error");
  }
};

/* ---------------- 9. Contracting & Projects (پیمانکاری) ---------------- */
async function loadContracting() {
  const empSel = $("#cntEmployer");
  empSel.innerHTML = state.customers.map(c => `<option value="${c.id}">${esc(c.title)} (کد: ${c.code})</option>`).join("");

  const contracts = await api(`/tenants/${state.tenant}/contracting/contracts`);
  const billCntSel = $("#billContractSelect");
  billCntSel.innerHTML = contracts.map(c => `<option value="${c.id}">${esc(c.title)} (${esc(c.contract_no)})</option>`).join("");

  const billings = await api(`/tenants/${state.tenant}/contracting/billings`);
  const tbody = $("#billingsTableBody");
  tbody.innerHTML = "";
  if (!billings.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="muted" style="text-align:center;">هیچ صورت‌وضعیتی ثبت نشده است.</td></tr>';
    return;
  }
  billings.forEach((b) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${esc(b.billing_no)}</strong></td>
      <td>${esc(b.contract_title || b.contract_id)}</td>
      <td>${toFa(b.billing_date)}</td>
      <td class="num">${money(b.gross_amount)}</td>
      <td class="num text-danger">${money(b.retention_amount)}</td>
      <td class="num text-danger">${money(b.sso_amount)}</td>
      <td class="num">${money(b.vat_amount)}</td>
      <td class="num font-bold text-success">${money(b.net_receivable)}</td>
      <td><span class="chip ${b.status === 'confirmed' ? 'ok' : 'warn'}">${b.status === 'confirmed' ? 'تایید و سند شده' : 'پیش‌نویس'}</span></td>
      <td>
        ${b.status === 'draft' ? `<button class="btn sm" onclick="confirmBillingRow('${b.id}')">تایید و صدور سند</button>` : '—'}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function saveContract() {
  const no = $("#cntNo").value.trim();
  const title = $("#cntTitle").value.trim();
  const amt = parseFloat($("#cntAmount").value || 0);
  const empId = $("#cntEmployer").value;
  if (!no || !title || amt <= 0) return toast("شماره، عنوان و مبلغ قرارداد الزامی است.", "error");

  const ret = parseFloat($("#cntRetention").value || 10) / 100;
  const sso = parseFloat($("#cntSso").value || 5) / 100;

  await api(`/tenants/${state.tenant}/contracting/contracts`, {
    method: "POST",
    body: {
      contract_no: no,
      title,
      total_amount: amt,
      employer_sub_ledger_id: empId,
      start_date: todayISO(),
      retention_rate: ret,
      sso_rate: sso
    }
  });
  toast("قرارداد پیمانکاری با موفقیت ثبت شد.", "ok");
  $("#cntNo").value = "";
  $("#cntTitle").value = "";
  $("#cntAmount").value = "";
  loadContracting();
}

async function submitProgressBilling() {
  const cntId = $("#billContractSelect").value;
  const bNo = $("#billNo").value.trim();
  const bDate = $("#billDate").value || todayISO();
  const gross = parseFloat($("#billGross").value || 0);
  if (!cntId || !bNo || gross <= 0) return toast("انتخاب قرارداد، شماره صورت‌وضعیت و مبلغ کارکرد ناخالص الزامی است.", "error");

  const res = await api(`/tenants/${state.tenant}/contracting/billings`, {
    method: "POST",
    body: {
      contract_id: cntId,
      billing_no: bNo,
      billing_date: bDate,
      gross_amount: gross,
      advance_amortization: 0.0
    }
  });
  toast(`صورت‌وضعیت ثبت شد. خالص قابل دریافت از کارفرما: ${money(res.net_receivable)} تومان`, "ok");
  $("#billNo").value = "";
  $("#billGross").value = "";
  loadContracting();
}

window.confirmBillingRow = async function(billingId) {
  if (!state.fy) return toast("سال مالی فعال یافت نشد.", "error");
  try {
    const res = await api(`/tenants/${state.tenant}/contracting/billings/${billingId}/confirm`, {
      method: "POST",
      body: {
        fiscal_year_id: state.fy.id
      }
    });
    toast("صورت‌وضعیت تایید و سند خودکار حسابداری پیمانکاری صادر شد.", "ok");
    loadContracting();
  } catch (e) {
    toast(e.message, "error");
  }
};

/* ---------------- 10. Module Licensing & Presets ---------------- */
async function loadModules() {
  try {
    const res = await api(`/tenants/${state.tenant}/modules`);
    state.modules = res.modules || [];
    state.presets = res.presets || [];
    syncNavVisibility();
  } catch (e) {
    console.error("Failed to load modules:", e);
  }
}

function syncNavVisibility() {
  const modMap = {};
  (state.modules || []).forEach((m) => {
    modMap[m.key] = m.is_enabled;
  });

  const navMap = {
    treasury: $("#navTreasury"),
    inventory: $("#navInventory"),
    invoicing: $("#navSales"),
    payroll: $("#navPayroll"),
    fixed_assets: $("#navFixedAssets"),
    manufacturing: $("#navManufacturing"),
    contracting: $("#navContracting"),
  };

  for (const [key, btn] of Object.entries(navMap)) {
    if (btn) {
      const isEnabled = modMap[key] !== false;
      btn.style.display = isEnabled ? "block" : "none";
    }
  }

  // If user is currently viewing a disabled module, redirect to dashboard
  const currentViewMod = {
    treasury: "treasury",
    inventory: "inventory",
    sales: "invoicing",
    payroll: "payroll",
    fixedAssets: "fixed_assets",
    manufacturing: "manufacturing",
    contracting: "contracting",
  }[state.view];

  if (currentViewMod && modMap[currentViewMod] === false) {
    toast(`ماژول این بخش غیرفعال است؛ به داشبورد هدایت شدید.`, "warn");
    go("dashboard");
  }

  const activeCount = (state.modules || []).filter((m) => m.is_enabled).length;
  const chip = $("#activeModulesCountChip");
  if (chip) chip.textContent = `${toFa(activeCount)} ماژول فعال`;
}

async function loadModulesView() {
  await loadModules();
  renderPresets();
  renderModulesGrid();
}

function renderPresets() {
  const wrap = $("#presetButtonsWrap");
  if (!wrap) return;
  wrap.innerHTML = "";

  (state.presets || []).forEach((p) => {
    const btn = document.createElement("button");
    btn.className = "btn ghost sm";
    btn.style.display = "flex";
    btn.style.alignItems = "center";
    btn.style.gap = "6px";
    btn.innerHTML = `<strong>${esc(p.title)}</strong>`;
    btn.title = p.description;
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const res = await api(`/tenants/${state.tenant}/modules/preset/${p.key}`, { method: "POST" });
        toast(res.message, "ok");
        await loadModulesView();
      } catch (e) {
        toast(e.message, "error");
      } finally {
        btn.disabled = false;
      }
    };
    wrap.appendChild(btn);
  });
}

function renderModulesGrid() {
  const grid = $("#modulesGrid");
  if (!grid) return;
  grid.innerHTML = "";

  (state.modules || []).forEach((m) => {
    const card = document.createElement("div");
    card.className = "card";
    card.style.display = "flex";
    card.style.flexDirection = "column";
    card.style.justifyContent = "space-between";
    card.style.border = m.is_enabled ? "1px solid rgba(16,185,129,0.35)" : "1px solid var(--border)";
    card.style.boxShadow = m.is_enabled ? "0 4px 12px rgba(16,185,129,0.06)" : "none";

    let badgeClass = "gray";
    let badgeText = "غیرفعال 🔒";
    if (m.is_core) {
      badgeClass = "ok";
      badgeText = "هسته پایه ⚡";
    } else if (!m.is_ready) {
      badgeClass = "warn";
      badgeText = "به‌زودی ⏳";
    } else if (m.is_enabled) {
      badgeClass = "ok";
      badgeText = "فعال و در دسترس ✅";
    }

    card.innerHTML = `
      <div>
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
          <div>
            <h3 style="margin:0 0 2px 0; font-size:16px;">${esc(m.title)}</h3>
            <div class="muted" style="font-size:12px;">${esc(m.subtitle || "")}</div>
          </div>
          <span class="badge ${badgeClass}">${badgeText}</span>
        </div>
        <p style="font-size:13px; color:var(--text); line-height:1.6; margin:10px 0;">${esc(m.description)}</p>
      </div>
      <div style="margin-top:15px; padding-top:12px; border-top:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
        <span class="muted" style="font-size:12px;">${m.is_core ? "پایه دائمی" : (m.activated_at ? "فعال در اشتراک" : "اختیاری")}</span>
        <div id="btnModWrap_${m.key}"></div>
      </div>
    `;

    const btnWrap = card.querySelector(`#btnModWrap_${m.key}`);
    if (m.is_core) {
      btnWrap.innerHTML = `<button class="btn sm ghost" disabled style="opacity:0.7;">غیرقابل تغییر</button>`;
    } else if (!m.is_ready) {
      btnWrap.innerHTML = `<button class="btn sm ghost" disabled style="opacity:0.5;">فاز بعدی</button>`;
    } else if (m.is_enabled) {
      const btn = document.createElement("button");
      btn.className = "btn sm ghost";
      btn.style.color = "#dc2626";
      btn.style.borderColor = "#fca5a5";
      btn.textContent = "غیرفعال‌سازی 🔒";
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          const res = await api(`/tenants/${state.tenant}/modules/${m.key}/toggle`, {
            method: "POST",
            body: { is_enabled: false }
          });
          toast(res.message, "ok");
          await loadModulesView();
        } catch (e) {
          toast(e.message, "error");
        } finally {
          btn.disabled = false;
        }
      };
      btnWrap.appendChild(btn);
    } else {
      const btn = document.createElement("button");
      btn.className = "btn sm";
      btn.textContent = "فعال‌سازی ماژول ⚡";
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          const res = await api(`/tenants/${state.tenant}/modules/${m.key}/toggle`, {
            method: "POST",
            body: { is_enabled: true }
          });
          toast(res.message, "ok");
          await loadModulesView();
        } catch (e) {
          toast(e.message, "error");
        } finally {
          btn.disabled = false;
        }
      };
      btnWrap.appendChild(btn);
    }

    grid.appendChild(card);
  });
}

async function init() {
  wire();
  renderTabs();
  setDefaultDates();
  const ok = await bootstrap(true);
  if (ok) {
    if (!$("#jeRows tbody").children.length) { jeRow(); jeRow(); }
    await refresh();
    toast("سامانه جامع مالی آربین آماده کار است.", "ok");
  } else {
    $("#sysInfo").innerHTML = 'داده‌ای موجود نیست؛ دکمه «راه‌اندازی داده نمایشی» را بزنید.';
  }
}

document.addEventListener("DOMContentLoaded", init);
