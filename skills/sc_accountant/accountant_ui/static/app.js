/* SC Accountant — Dashboard Application */

const API = "";
const REFRESH_INTERVAL = 1800000; // 30 minutes
const LOCATION_POLL_INTERVAL = 30000; // 30 seconds

let currentTab = "balancesheet";
let currentPage = 0;
let currentPeriod = "month";
let refreshTimer = null;
let locationPollTimer = null;

// Opportunities filter state (cached on load)
let cachedPlayerLocation = null;
let cachedShips = null;
let selectedLocation = ""; // "" = All Locations, "__my_location__" = My Location
let selectedCargoScu = 0;
let selectedShipName = ""; // tracks which ship is selected (by display label)

// Category cache for forms
let cachedCategories = null;

// Tab help text shown in the footer
const TAB_DESCRIPTIONS = {
  balancesheet: "Financial snapshot showing total assets and net worth.",
  operations: "Income statement showing revenue, costs, and profit margins for the selected period.",
  ledger: "Complete record of all transactions — income and expenses, sorted by date.",
  fleet: "Registry of owned ships, vehicles, and equipment with purchase prices and market values.",
  portfolio: "Open commodity positions with cost basis, market value, and unrealized profit/loss.",
  opportunities: "Trade route suggestions ranked by profit margin, based on live market data.",
  statistics: "Visual analytics and charts of your financial activity over time.",
  about: "About SC Accountant — project info and remote access.",
};

// --- Initialization ---

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupPeriodSelect();
  setupModal();
  setupTableWrapping();
  loadBalance();
  loadTab(currentTab);
  loadOpportunityData();
  loadCategories();
  startAutoRefresh();
  startLocationPolling();
});

function setupTableWrapping() {
  const content = document.getElementById("content");
  if (!content) return;

  const wrapTables = () => {
    content.querySelectorAll("table").forEach((table) => {
      const parent = table.parentElement;
      if (parent && parent.classList.contains("table-wrap")) return;
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    });
  };

  new MutationObserver(wrapTables).observe(content, {
    childList: true,
    subtree: true,
  });
  wrapTables();
}

async function loadOpportunityData() {
  const [playerLoc, ships] = await Promise.all([
    fetchJSON("/api/player-location"),
    fetchJSON("/api/ships"),
  ]);
  cachedPlayerLocation = playerLoc;
  cachedShips = ships;
}

function startLocationPolling() {
  if (locationPollTimer) clearInterval(locationPollTimer);
  locationPollTimer = setInterval(pollPlayerLocation, LOCATION_POLL_INTERVAL);
}

async function pollPlayerLocation() {
  const newLoc = await fetchJSON("/api/player-location");
  if (!newLoc) return;

  const oldName = cachedPlayerLocation && cachedPlayerLocation.available
    ? (cachedPlayerLocation.location_name || "")
    : "";
  const newName = newLoc.available ? (newLoc.location_name || "") : "";

  cachedPlayerLocation = newLoc;

  // If location changed and we're on the opportunities tab, refresh it
  if (oldName !== newName && currentTab === "opportunities") {
    renderOpportunities();
  }
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentTab = btn.dataset.tab;
      currentPage = 0;
      loadTab(currentTab);
    });
  });
}

function setupPeriodSelect() {
  const sel = document.getElementById("period-select");
  sel.addEventListener("change", () => {
    currentPeriod = sel.value;
    currentPage = 0;
    loadTab(currentTab);
  });
}

let lastDataVersion = 0;

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  // Poll the data version counter every 2s — refreshes only when data changes
  refreshTimer = setInterval(async () => {
    try {
      const res = await fetch(API + "/api/version?_=" + Date.now(), { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      if (data.version !== lastDataVersion) {
        lastDataVersion = data.version;
        loadBalance();
        loadTab(currentTab);
      }
    } catch (e) {
      // Server unreachable — skip this cycle
    }
  }, 2000);
}

// --- API Helpers ---

async function fetchJSON(url) {
  try {
    const res = await fetch(API + url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    updateStatus("Connected");
    return await res.json();
  } catch (err) {
    updateStatus("Disconnected");
    return null;
  }
}

function updateStatus() {
  // Status display removed — help text now lives in footer
}

function fmt(amount) {
  if (amount == null) return "0 aUEC";
  return amount.toLocaleString("en-US", { maximumFractionDigits: 0 }) + " aUEC";
}

function fmtPct(value) {
  if (value == null) return "0%";
  return value.toFixed(1) + "%";
}

function signClass(amount) {
  if (amount > 0) return "positive";
  if (amount < 0) return "negative";
  return "";
}

// --- Balance ---

async function loadBalance() {
  const data = await fetchJSON("/api/balance");
  if (!data) return;
  const el = document.getElementById("balance");
  el.textContent = data.formatted;
}

// --- Network Info ---

async function renderAbout() {
  const content = document.getElementById("content");

  let html = '<div class="about-page">';
  html += '<div class="about-section">';
  html += "<h2>SC Accountant</h2>";
  html += "<p>A full-featured accounting companion for Star Citizen, built as a Wingman AI skill.</p>";
  html += "<p>A solo-player accounting companion for Star Citizen. Track transactions, "
    + "manage assets, analyze trade opportunities, and monitor your financial performance "
    + "across all gameplay activities.</p>";
  html += "</div>";

  html += '<div class="about-section">';
  html += "<h3>Features</h3>";
  html += "<ul>";
  html += "<li><strong>Balance Sheet</strong> — Assets and net worth overview</li>";
  html += "<li><strong>Operations</strong> — Income statement with revenue, costs, and margins</li>";
  html += "<li><strong>Ledger</strong> — Complete transaction history</li>";
  html += "<li><strong>My Assets</strong> — Ship, vehicle, and equipment registry</li>";
  html += "<li><strong>Portfolio</strong> — Commodity positions with unrealized P&L</li>";
  html += "<li><strong>Opportunities</strong> — Trade routes ranked by profit margin</li>";
  html += "<li><strong>Statistics</strong> — Visual charts and financial analytics</li>";
  html += "</ul>";
  html += "</div>";

  html += '<div class="about-section">';
  html += "<h3>Voice Commands</h3>";
  html += "<p>All features are accessible via voice through your Wingman AI assistant. "
    + "Ask your wingman to record transactions, check your balance, open the dashboard, and more.</p>";
  html += "</div>";

  // Remote access section — always shown so phones/tablets can scan the QR
  const netData = await fetchJSON("/api/network");
  if (netData) {
    html += '<div class="about-section">';
    html += "<h3>Remote Access</h3>";
    html += "<p>Scan or tap to open this dashboard on a phone or tablet on the same network:</p>";
    html += '<div class="about-remote">';
    if (netData.qr_svg) {
      html += '<div class="about-qr">' + netData.qr_svg + "</div>";
    }
    html += `<a href="${escHtml(netData.lan_url)}" target="_blank" class="lan-link about-lan-url">${escHtml(netData.lan_url)}</a>`;
    html += "</div>";
    html += "</div>";
  }

  html += '<div class="about-section">';
  html += "<h3>Support</h3>";
  html += '<p>For documentation, updates, and support visit the official forum post on the Wingman AI Discord:</p>';
  html += '<p><a href="https://discord.com/channels/1173573578604687360/1477699669336260682" target="_blank" class="lan-link">Wingman AI Discord — SC Accountant</a></p>';
  html += "</div>";

  html += '<div class="about-section about-credits">';
  html += "<p>Author: Mallachi</p>";
  html += "</div>";

  // Danger Zone — semi-hidden destructive reset. Used after a Star Citizen
  // economy wipe when the player needs to clear all accountant data.
  html += '<div class="about-section danger-zone">';
  html += '<details class="danger-details">';
  html += '<summary class="danger-summary">Danger Zone</summary>';
  html += '<div class="danger-body">';
  html += '<p class="danger-note">If Star Citizen has reset your in-game economy, '
    + 'you can wipe every saved accountant record (transactions, balance, positions, '
    + 'fleet, opportunities, sessions, budgets, sync cursor) to start fresh. '
    + 'Market reference data is preserved. <strong>This cannot be undone.</strong></p>';
  html += '<button id="danger-reset-btn" type="button" class="btn-danger">Reset all accountant data</button>';
  html += '</div></details>';
  html += '</div>';

  html += "</div>";

  content.innerHTML = html;

  const resetBtn = document.getElementById("danger-reset-btn");
  if (resetBtn) {
    resetBtn.addEventListener("click", openResetConfirmModal);
  }
}

// --- Reset confirmation modal ---

function openResetConfirmModal() {
  const overlay = document.getElementById("modal-overlay");
  const titleEl = document.getElementById("modal-title");
  const bodyEl = document.getElementById("modal-body");
  const statusEl = document.getElementById("modal-status");
  const saveBtn = document.getElementById("modal-save");
  const cancelBtn = document.getElementById("modal-cancel");
  const closeBtn = document.getElementById("modal-close");
  const form = document.getElementById("modal-form");
  if (!overlay || !titleEl || !bodyEl || !saveBtn || !form) return;

  titleEl.textContent = "Reset all accountant data?";
  bodyEl.innerHTML =
    '<p class="modal-warning">Are you really sure about this? '
    + 'Every saved transaction, balance, position, fleet entry, trade order, '
    + 'session, budget and opportunity will be permanently deleted. '
    + 'Market reference data is preserved.</p>'
    + '<p class="modal-warning"><strong>This cannot be undone.</strong></p>'
    + '<label for="reset-confirm-input" class="modal-label">'
    + 'Type <code>RESET</code> to enable the confirm button:</label>'
    + '<input id="reset-confirm-input" type="text" autocomplete="off" '
    + 'spellcheck="false" placeholder="RESET" class="modal-input" />';

  if (statusEl) statusEl.textContent = "";
  saveBtn.textContent = "Delete everything";
  saveBtn.classList.add("btn-danger");
  saveBtn.classList.remove("btn-primary");
  saveBtn.disabled = true;

  const input = document.getElementById("reset-confirm-input");
  if (input) {
    input.addEventListener("input", () => {
      saveBtn.disabled = input.value.trim() !== "RESET";
    });
    setTimeout(() => input.focus(), 50);
  }

  const cleanup = () => {
    overlay.style.display = "none";
    saveBtn.classList.remove("btn-danger");
    saveBtn.classList.add("btn-primary");
    saveBtn.textContent = "Save";
    saveBtn.disabled = false;
    form.onsubmit = null;
    if (cancelBtn) cancelBtn.onclick = null;
    if (closeBtn) closeBtn.onclick = null;
  };

  form.onsubmit = async (ev) => {
    ev.preventDefault();
    if (input && input.value.trim() !== "RESET") return;
    saveBtn.disabled = true;
    saveBtn.textContent = "Deleting...";
    try {
      const resp = await fetch("/api/reset", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({confirmation: "RESET"}),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        if (statusEl) {
          statusEl.textContent = err.error || "Reset failed.";
        }
        saveBtn.disabled = false;
        saveBtn.textContent = "Delete everything";
        return;
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = "Reset failed: " + e.message;
      saveBtn.disabled = false;
      saveBtn.textContent = "Delete everything";
      return;
    }
    cleanup();
    // Force a full reload so every cached chart and tab clears.
    window.location.reload();
  };

  if (cancelBtn) cancelBtn.onclick = cleanup;
  if (closeBtn) closeBtn.onclick = cleanup;

  overlay.style.display = "flex";
}

// --- Tab Router ---

function loadTab(tab) {
  const content = document.getElementById("content");
  content.innerHTML = '<div class="loading">Loading...</div>';
  const helpEl = document.getElementById("tab-help-text");
  if (helpEl) helpEl.textContent = TAB_DESCRIPTIONS[tab] || "";

  switch (tab) {
    case "ledger": return renderLedger();
    case "fleet": return renderFleet();
    case "operations": return renderOperations();
    case "balancesheet": return renderBalanceSheet();
    case "portfolio": return renderPortfolio();
    case "opportunities": return renderOpportunities();
    case "statistics": return renderStatistics();
    case "about": return renderAbout();
  }
}

// --- Ledger Tab ---

async function renderLedger() {
  const data = await fetchJSON(
    `/api/transactions?page=${currentPage}&period=${currentPeriod}&page_size=25`
  );
  if (!data) return showEmpty("No data available");

  const content = document.getElementById("content");
  if (data.transactions.length === 0) {
    return showEmpty("No transactions recorded");
  }

  const cols = ["date", "type", "category", "amount", "description", "notes", "location"];
  let html = `<table id="ledger-table">
    <thead>
      <tr>
        <th>Date</th><th>Type</th><th>Category</th>
        <th>Amount</th><th>Description</th><th>Notes</th><th>Location</th>
      </tr>
      ${buildFilterRow(cols)}
    </thead><tbody>`;

  for (let i = 0; i < data.transactions.length; i++) {
    const t = data.transactions[i];
    const cls = t.type === "income" ? "income" : "expense";
    const sign = t.type === "income" ? "+" : "-";
    html += `<tr class="clickable-row" data-idx="${i}"
      data-date="${escHtml(formatTimestamp(t.timestamp))}"
      data-type="${escHtml(t.type)}"
      data-category="${escHtml(t.category)}"
      data-amount="${t.amount}"
      data-description="${escHtml(t.description)}"
      data-notes="${escHtml(t.notes || "")}"
      data-location="${escHtml(t.location)}">
      <td>${formatTimestamp(t.timestamp)}</td>
      <td class="${cls}">${sign}</td>
      <td>${t.category}</td>
      <td class="num ${cls}">${fmt(t.amount)}</td>
      <td title="${escHtml(t.description)}">${escHtml(t.description)}</td>
      <td>${escHtml(t.notes || "")}</td>
      <td>${escHtml(t.location)}</td>
    </tr>`;
  }

  html += "</tbody></table>";
  html += renderPagination(data.page, data.total_pages);

  content.innerHTML = html;
  setupPagination();

  wireTableFilters("ledger-table", content);

  // Wire row clicks for editing
  content.querySelectorAll(".clickable-row").forEach((row) => {
    row.addEventListener("click", () => {
      const txn = data.transactions[parseInt(row.dataset.idx)];
      openEditTransactionForm(txn);
    });
  });
}

// --- Fleet Tab ---

async function renderFleet() {
  const [fleetData, summaryData] = await Promise.all([
    fetchJSON(`/api/fleet?status=active`),
    fetchJSON("/api/fleet/summary"),
  ]);

  const content = document.getElementById("content");
  if (!fleetData || fleetData.total === 0) {
    content.innerHTML = actionBar("+ Add Asset");
    wireActionButton(openAssetForm);
    return;
  }

  let html = actionBar("+ Add Asset");
  html += '<div class="summary-row">';
  html += summaryCard("Total Assets", summaryData.total_count || 0);
  html += summaryCard("Total Value", fmt(summaryData.total_value || 0));

  if (summaryData.by_type) {
    for (const [type, info] of Object.entries(summaryData.by_type)) {
      html += summaryCard(
        type.charAt(0).toUpperCase() + type.slice(1) + "s",
        info.count,
        fmt(info.value)
      );
    }
  }
  html += "</div>";

  const fleetCols = ["name", "type", "purchase", "market", "location", "notes"];
  html += `<table id="fleet-table">
    <thead><tr>
      <th>Name</th><th>Type</th><th>Purchase Price</th>
      <th>Market Value</th><th>Location</th><th>Notes</th>
    </tr>
    ${buildFilterRow(fleetCols)}
    </thead><tbody>`;

  for (let i = 0; i < fleetData.assets.length; i++) {
    const a = fleetData.assets[i];
    html += `<tr class="clickable-row" data-idx="${i}"
      data-name="${escHtml(a.name)}"
      data-type="${escHtml(a.asset_type)}"
      data-purchase="${a.purchase_price}"
      data-market="${a.estimated_market_value}"
      data-location="${escHtml(a.location)}"
      data-notes="${escHtml(a.notes)}">
      <td><strong>${escHtml(a.name)}</strong></td>
      <td>${a.asset_type}</td>
      <td class="num">${a.formatted_purchase_price}</td>
      <td class="num">${a.estimated_market_value ? a.formatted_market_value : "Unknown"}</td>
      <td>${escHtml(a.location)}</td>
      <td>${escHtml(a.notes)}</td>
    </tr>`;
  }

  html += "</tbody></table>";
  content.innerHTML = html;
  wireActionButton(openAssetForm);
  wireTableFilters("fleet-table", content);

  // Wire row clicks for editing
  content.querySelectorAll(".clickable-row").forEach((row) => {
    row.addEventListener("click", () => {
      const asset = fleetData.assets[parseInt(row.dataset.idx)];
      openEditAssetForm(asset);
    });
  });
}

// --- Orders (Planned Purchase/Sales Orders) ---

async function renderOperations() {
  const data = await fetchJSON(`/api/income-statement?period=${currentPeriod}`);
  if (!data) return showEmpty("No data available");

  const content = document.getElementById("content");
  let html = '<div class="summary-row">';
  html += summaryCard("Revenue", fmt(data.revenue), null, "positive");
  html += summaryCard("COGS", fmt(data.cogs), null, "negative");
  html += summaryCard(
    "Gross Margin",
    fmt(data.gross_margin),
    fmtPct(data.gross_margin_pct)
  );
  html += summaryCard(
    "Net Profit",
    fmt(data.net_operating_profit),
    fmtPct(data.net_margin_pct),
    data.net_operating_profit >= 0 ? "positive" : "negative"
  );
  html += "</div>";

  // Revenue breakdown
  html += '<div class="statement-section"><h3>Revenue</h3>';
  if (data.revenue_by_category) {
    for (const [cat, amount] of Object.entries(data.revenue_by_category)) {
      const pct =
        data.revenue > 0 ? ((amount / data.revenue) * 100).toFixed(1) : "0";
      html += statementRow(cat, fmt(amount), pct + "%", true);
    }
  }
  html += statementRow("Total Revenue", fmt(data.revenue), "", false, true);
  html += "</div>";

  // COGS
  if (data.cogs > 0) {
    html += '<div class="statement-section"><h3>Cost of Goods Sold</h3>';
    if (data.cogs_by_category) {
      for (const [cat, amount] of Object.entries(data.cogs_by_category)) {
        html += statementRow(cat, "-" + fmt(amount), "", true);
      }
    }
    html += statementRow("Total COGS", "-" + fmt(data.cogs), "", false, true);
    html += "</div>";
  }

  // OpEx
  if (data.opex > 0) {
    html += '<div class="statement-section"><h3>Operating Expenses</h3>';
    if (data.opex_by_category) {
      for (const [cat, amount] of Object.entries(data.opex_by_category)) {
        html += statementRow(cat, "-" + fmt(amount), "", true);
      }
    }
    html += statementRow("Total OpEx", "-" + fmt(data.opex), "", false, true);
    html += "</div>";
  }

  // Activity margins
  if (data.activity_margins && data.activity_margins.length > 0) {
    html += '<div class="statement-section"><h3>By Activity</h3>';
    for (const am of data.activity_margins) {
      if (am.revenue > 0 || am.costs > 0) {
        const name = am.activity.replace(/_/g, " ");
        const cap = name.charAt(0).toUpperCase() + name.slice(1);
        html += statementRow(cap, fmt(am.margin), fmtPct(am.margin_pct), true);
      }
    }
    html += "</div>";
  }

  // CAPEX (investing expenses)
  if (data.capex > 0) {
    html += '<div class="statement-section"><h3>Capital Expenditures</h3>';
    if (data.capex_by_category) {
      for (const [cat, amount] of Object.entries(data.capex_by_category)) {
        html += statementRow(cat, "-" + fmt(amount), "", true);
      }
    }
    html += statementRow("Total CAPEX", "-" + fmt(data.capex), "", false, true);
    html += "</div>";
  }

  // Cash Flow Summary (derived from income statement data)
  const opInflows = data.revenue;
  const opOutflows = data.cogs + data.opex;
  const opNet = opInflows - opOutflows;
  const invNet = -data.capex;
  const netCash = opNet + invNet;

  html += '<div class="statement-section"><h3>Cash Flow</h3>';
  html += statementRow("Operating Inflows", "+" + fmt(opInflows), "", true);
  html += statementRow("Operating Outflows", "-" + fmt(opOutflows), "", true);
  html += statementRow("Operating Net", fmt(opNet), "", false, true);
  if (data.capex > 0) {
    html += statementRow("Investing Outflows", "-" + fmt(data.capex), "", true);
    html += statementRow("Investing Net", fmt(invNet), "", false, true);
  }
  html += statementRow("Net Cash Change", fmt(netCash), "", false, true);
  html += "</div>";

  content.innerHTML = html;
}

// --- Balance Sheet ---

async function renderBalanceSheet() {
  const data = await fetchJSON("/api/balance-sheet");
  if (!data) return showEmpty("No data available");

  const content = document.getElementById("content");
  const ast = data.assets;
  const eq = data.equity;

  let html = actionBar("+ Set Balance");
  html += '<div class="summary-row">';
  html += summaryCard(
    "Net Worth",
    fmt(eq.net_worth),
    null,
    eq.net_worth >= 0 ? "positive" : "negative"
  );
  html += summaryCard("Total Assets", fmt(ast.total), null, "positive");
  html += summaryCard("Cash", fmt(ast.cash), null, "positive");
  html += "</div>";

  html += '<div class="statement-section"><h3>Assets</h3>';
  html += statementRow("Cash", fmt(ast.cash));
  if (ast.ships > 0) html += statementRow(`Ships (${ast.ships_count})`, fmt(ast.ships));
  if (ast.components > 0) html += statementRow("Components", fmt(ast.components));
  if (ast.vehicles > 0) html += statementRow("Vehicles", fmt(ast.vehicles));
  if (ast.cargo > 0) html += statementRow("Cargo (Positions)", fmt(ast.cargo));
  html += statementRow("Total Assets", fmt(ast.total), "", false, true);
  html += "</div>";

  html += '<div class="statement-section"><h3>Equity</h3>';
  html += statementRow("Net Worth", fmt(eq.net_worth), "", false, true);
  html += "</div>";

  content.innerHTML = html;
  wireActionButton(openBalanceForm);
}

// --- Portfolio ---

async function renderPortfolio() {
  const data = await fetchJSON("/api/positions");
  if (!data || data.total === 0) {
    const content = document.getElementById("content");
    content.innerHTML = actionBar("+ Record Purchase", "+ Record Sale");
    wireActionButton(openPurchaseForm, 0);
    wireActionButton(openSaleForm, 1);
    return;
  }

  const content = document.getElementById("content");
  const totalInvested = data.positions.reduce((s, p) => s + p.buy_total, 0);
  const totalPnl = data.positions.reduce((s, p) => s + p.unrealized_pnl, 0);

  let html = actionBar("+ Record Purchase", "+ Record Sale");
  html += '<div class="summary-row">';
  html += summaryCard("Positions", data.total);
  html += summaryCard("Invested", fmt(totalInvested));
  html += summaryCard(
    "Unrealized P&L",
    fmt(totalPnl),
    null,
    totalPnl >= 0 ? "positive" : "negative"
  );
  html += "</div>";

  const portCols = ["commodity", "qty", "invested", "market", "pnl", "comment"];
  html += `<table id="portfolio-table">
    <thead><tr>
      <th>Commodity</th><th>Qty</th><th>Invested</th>
      <th title="Based on average sell price across all terminals">Avg Market Value</th><th>P&L</th><th>Comment</th>
    </tr>
    ${buildFilterRow(portCols)}
    </thead><tbody>`;

  for (let i = 0; i < data.positions.length; i++) {
    const p = data.positions[i];
    const cls = signClass(p.unrealized_pnl);
    const sign = p.unrealized_pnl >= 0 ? "+" : "";
    html += `<tr class="clickable-row" data-idx="${i}"
      data-commodity="${escHtml(p.commodity_name)}"
      data-qty="${p.quantity}"
      data-invested="${p.buy_total}"
      data-market="${p.market_value || ""}"
      data-pnl="${p.unrealized_pnl}">
      <td>${p.commodity_name.startsWith("Unknown (")
        ? `<span title="Details missing from Star Citizen logs (CIG fucked up).">${escHtml(p.commodity_name)}</span>`
        : escHtml(p.commodity_name)}</td>
      <td class="num">${p.quantity} ${escHtml((p.quantity_unit || "scu").toUpperCase())}</td>
      <td class="num">${p.formatted_invested}</td>
      <td class="num">${p.market_value ? p.formatted_market : "Unknown"}</td>
      <td class="num ${cls}">${p.market_value ? sign + p.formatted_pnl : "Unknown"}</td>
      <td>${escHtml(p.notes || "")}</td>
    </tr>`;
  }

  html += "</tbody></table>";
  content.innerHTML = html;
  wireActionButton(openPurchaseForm, 0);
  wireActionButton(openSaleForm, 1);
  wireTableFilters("portfolio-table", content);

  // Wire row clicks for editing
  content.querySelectorAll(".clickable-row").forEach((row) => {
    row.addEventListener("click", () => {
      const pos = data.positions[parseInt(row.dataset.idx)];
      openEditPositionForm(pos);
    });
  });
}

// --- Opportunities ---

async function renderOpportunities() {
  // Refresh player location first so the dropdown label is current
  const freshPlayerLoc = await fetchJSON("/api/player-location");
  if (freshPlayerLoc) cachedPlayerLocation = freshPlayerLoc;

  // Resolve "My Location" sentinel to actual location name for the API
  const resolvedLocation =
    selectedLocation === "__my_location__" &&
    cachedPlayerLocation &&
    cachedPlayerLocation.available
      ? cachedPlayerLocation.location_name || ""
      : "";

  let url = "/api/opportunities";
  const params = [];
  if (resolvedLocation) params.push(`location=${encodeURIComponent(resolvedLocation)}`);
  if (selectedCargoScu > 0) params.push(`cargo_scu=${selectedCargoScu}`);
  if (params.length > 0) url += "?" + params.join("&");

  const data = await fetchJSON(url);

  const content = document.getElementById("content");

  // Build filter bar
  let html = '<div class="filter-bar">';
  html += buildLocationDropdown();
  html += buildShipDropdown();
  html += '<button id="opp-refresh-btn" class="refresh-btn" title="Refresh">Refresh</button>';
  html += "</div>";

  if (!data || data.total === 0) {
    html += '<div class="empty-state"><div class="icon">--</div><div>No trade opportunities available</div></div>';

    content.innerHTML = html;
    setupOpportunityFilters();
    return;
  }

  const oppCols = ["commodity", "buyloc", "buyterminal", "sellloc", "sellterminal", "available", "effective", "margin", "profit"];
  html += `<table id="opp-table">
    <thead><tr>
      <th>Commodity</th><th>Buy Location</th><th>Buy Terminal</th>
      <th>Sell Location</th><th>Sell Terminal</th>
      <th>Available</th><th>Effective</th>
      <th>Margin/SCU</th><th>Est. Profit</th>
    </tr>
    ${buildFilterRow(oppCols)}
    </thead><tbody>`;

  for (const o of data.opportunities) {
    html += `<tr
      data-commodity="${escHtml(o.commodity_name)}"
      data-buyloc="${escHtml(o.buy_location)}"
      data-buyterminal="${escHtml(o.buy_terminal)}"
      data-sellloc="${escHtml(o.sell_location)}"
      data-sellterminal="${escHtml(o.sell_terminal)}"
      data-available="${escHtml(o.formatted_available)}"
      data-effective="${escHtml(o.formatted_effective)}"
      data-margin="${escHtml(o.formatted_margin)}"
      data-profit="${escHtml(o.formatted_profit)}">
      <td>${escHtml(o.commodity_name)}</td>
      <td>${escHtml(o.buy_location)}</td>
      <td>${escHtml(o.buy_terminal)}</td>
      <td>${escHtml(o.sell_location)}</td>
      <td>${escHtml(o.sell_terminal)}</td>
      <td class="num">${o.formatted_available}</td>
      <td class="num">${o.formatted_effective}</td>
      <td class="num positive">${o.formatted_margin}/SCU</td>
      <td class="num positive">${o.formatted_profit}</td>
    </tr>`;
  }

  html += "</tbody></table>";
  content.innerHTML = html;
  setupOpportunityFilters();
  wireTableFilters("opp-table", content);
}

function buildLocationDropdown() {
  const locName =
    cachedPlayerLocation && cachedPlayerLocation.available
      ? cachedPlayerLocation.location_name || ""
      : "";
  const myLocLabel = locName ? `My Location — ${escHtml(locName)}` : "My Location (unavailable)";

  let html = '<select id="location-select" class="filter-select">';
  html += `<option value="__my_location__"${selectedLocation === "__my_location__" ? " selected" : ""}>${myLocLabel}</option>`;
  html += `<option value=""${selectedLocation === "" ? " selected" : ""}>All Locations</option>`;
  html += "</select>";
  return html;
}

function buildShipDropdown() {
  let html = '<select id="ship-select" class="filter-select">';
  html += '<option value="0|">All Ships (no cargo limit)</option>';

  if (cachedShips && cachedShips.length > 0) {
    const sorted = [...cachedShips].sort((a, b) => {
      const nameA = `${a.manufacturer} ${a.name}`.toLowerCase();
      const nameB = `${b.manufacturer} ${b.name}`.toLowerCase();
      return nameA.localeCompare(nameB);
    });
    for (const ship of sorted) {
      const label = `${ship.manufacturer} ${ship.name}`;
      const val = `${ship.cargo_scu}|${label}`;
      html += `<option value="${escHtml(val)}">${escHtml(label)} (${ship.cargo_scu} SCU)</option>`;
    }
  }

  html += "</select>";
  return html;
}

function setupOpportunityFilters() {
  const locSel = document.getElementById("location-select");
  const shipSel = document.getElementById("ship-select");
  const refreshBtn = document.getElementById("opp-refresh-btn");

  if (locSel) {
    locSel.addEventListener("change", () => {
      selectedLocation = locSel.value;
      renderOpportunities();
    });
  }

  if (shipSel) {
    const storedVal = `${selectedCargoScu}|${selectedShipName}`;
    shipSel.value = storedVal;
    shipSel.addEventListener("change", () => {
      const parts = shipSel.value.split("|");
      selectedCargoScu = parseFloat(parts[0]) || 0;
      selectedShipName = parts.slice(1).join("|");
      renderOpportunities();
    });
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", async () => {
      refreshBtn.disabled = true;
      refreshBtn.textContent = "Refreshing...";
      const genLocation =
        selectedLocation === "__my_location__" &&
        cachedPlayerLocation &&
        cachedPlayerLocation.available
          ? cachedPlayerLocation.location_name || ""
          : "";
      try {
        await fetch("/api/opportunities/refresh", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({location: genLocation}),
        });
      } catch (e) { /* ignore */ }
      refreshBtn.textContent = "Refresh";
      refreshBtn.disabled = false;
      renderOpportunities();
    });
  }
}

// --- Statistics Tab ---

let statsCharts = []; // track chart instances for cleanup

function destroyStatsCharts() {
  for (const c of statsCharts) {
    try { c.destroy(); } catch (_) { /* ignore */ }
  }
  statsCharts = [];
}

const CHART_COLORS = {
  income: "#3fb950",
  expense: "#f85149",
  net: "#58a6ff",
  balance: "#d2a8ff",
  grid: "rgba(48, 54, 61, 0.6)",
  text: "#8b949e",
  palette: [
    "#58a6ff", "#3fb950", "#f85149", "#d29922", "#db6d28",
    "#d2a8ff", "#a5d6ff", "#7ee787", "#ffa657", "#ff7b72",
    "#79c0ff", "#56d364", "#e3b341", "#f0883e", "#bc8cff",
  ],
};

function chartDefaults() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: CHART_COLORS.text, font: { size: 11 } } },
      tooltip: { backgroundColor: "#161b22", titleColor: "#e6edf3", bodyColor: "#e6edf3", borderColor: "#30363d", borderWidth: 1 },
    },
    scales: {
      x: { ticks: { color: CHART_COLORS.text, font: { size: 10 } }, grid: { color: CHART_COLORS.grid } },
      y: { ticks: { color: CHART_COLORS.text, font: { size: 10 } }, grid: { color: CHART_COLORS.grid } },
    },
  };
}

async function renderStatistics() {
  destroyStatsCharts();
  const content = document.getElementById("content");

  // Default date range: last 30 days
  const now = new Date();
  const thirtyAgo = new Date(now);
  thirtyAgo.setDate(thirtyAgo.getDate() - 30);
  const defaultFrom = thirtyAgo.toISOString().substring(0, 10);
  const defaultTo = now.toISOString().substring(0, 10);

  let html = '<div class="stats-controls">';
  html += '<label>From <input type="date" id="stats-from" value="' + defaultFrom + '"></label>';
  html += '<label>To <input type="date" id="stats-to" value="' + defaultTo + '"></label>';
  html += '<select id="stats-granularity">';
  html += '<option value="daily" selected>Daily</option>';
  html += '<option value="weekly">Weekly</option>';
  html += '<option value="monthly">Monthly</option>';
  html += '</select>';
  html += '<button id="stats-apply" class="btn-primary" style="padding:4px 14px;font-size:12px;">Apply</button>';
  html += '</div>';

  // Summary cards
  html += '<div class="summary-row" id="stats-summary"></div>';

  // Chart grid
  html += '<div class="stats-grid">';
  html += '<div class="chart-panel chart-wide"><h3>Revenue vs Expenses</h3><div class="chart-container"><canvas id="chart-rev-exp"></canvas></div></div>';
  html += '<div class="chart-panel chart-wide"><h3>Net Profit</h3><div class="chart-container"><canvas id="chart-net"></canvas></div></div>';
  html += '<div class="chart-panel chart-wide"><h3>Running Balance</h3><div class="chart-container"><canvas id="chart-balance"></canvas></div></div>';
  html += '<div class="chart-panel"><h3>Income by Category</h3><div class="chart-container chart-square"><canvas id="chart-income-cat"></canvas></div></div>';
  html += '<div class="chart-panel"><h3>Expenses by Category</h3><div class="chart-container chart-square"><canvas id="chart-expense-cat"></canvas></div></div>';
  html += '<div class="chart-panel"><h3>Activity Breakdown</h3><div class="chart-container chart-square"><canvas id="chart-activity"></canvas></div></div>';
  html += '<div class="chart-panel chart-wide"><h3>Top Commodities (Net Profit)</h3><div class="chart-container"><canvas id="chart-commodities"></canvas></div></div>';
  html += '</div>';

  content.innerHTML = html;

  // Wire apply button and initial load
  const applyBtn = document.getElementById("stats-apply");
  applyBtn.addEventListener("click", () => loadStatsData());
  document.getElementById("stats-from").addEventListener("change", () => loadStatsData());
  document.getElementById("stats-to").addEventListener("change", () => loadStatsData());
  document.getElementById("stats-granularity").addEventListener("change", () => loadStatsData());

  loadStatsData();
}

async function loadStatsData() {
  const dateFrom = document.getElementById("stats-from").value;
  const dateTo = document.getElementById("stats-to").value;
  const granularity = document.getElementById("stats-granularity").value;

  const params = [];
  if (dateFrom) params.push("date_from=" + dateFrom);
  if (dateTo) params.push("date_to=" + dateTo);
  params.push("granularity=" + granularity);

  const data = await fetchJSON("/api/statistics?" + params.join("&"));
  if (!data) return;

  destroyStatsCharts();

  // Summary cards
  const sumEl = document.getElementById("stats-summary");
  if (sumEl && data.totals) {
    const t = data.totals;
    sumEl.innerHTML =
      summaryCard("Transactions", t.transaction_count) +
      summaryCard("Total Income", fmt(t.income), null, "positive") +
      summaryCard("Total Expenses", fmt(t.expenses), null, "negative") +
      summaryCard("Net Profit", fmt(t.net), null, t.net >= 0 ? "positive" : "negative");
  }

  const tl = data.timeline || [];
  const labels = tl.map(d => d.date);

  // 1) Revenue vs Expenses — bar chart
  statsCharts.push(new Chart(document.getElementById("chart-rev-exp"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Income", data: tl.map(d => d.income), backgroundColor: CHART_COLORS.income + "cc", borderColor: CHART_COLORS.income, borderWidth: 1 },
        { label: "Expenses", data: tl.map(d => d.expenses), backgroundColor: CHART_COLORS.expense + "cc", borderColor: CHART_COLORS.expense, borderWidth: 1 },
      ],
    },
    options: { ...chartDefaults(), plugins: { ...chartDefaults().plugins, legend: { display: true, labels: { color: CHART_COLORS.text } } } },
  }));

  // 2) Net Profit — line with gradient fill
  const netCtx = document.getElementById("chart-net").getContext("2d");
  const netGradient = netCtx.createLinearGradient(0, 0, 0, 250);
  netGradient.addColorStop(0, "rgba(88, 166, 255, 0.3)");
  netGradient.addColorStop(1, "rgba(88, 166, 255, 0.0)");
  statsCharts.push(new Chart(netCtx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Net Profit",
        data: tl.map(d => d.net),
        borderColor: CHART_COLORS.net,
        backgroundColor: netGradient,
        fill: true,
        tension: 0.3,
        pointRadius: tl.length > 60 ? 0 : 3,
        pointHoverRadius: 5,
      }],
    },
    options: { ...chartDefaults(), plugins: { ...chartDefaults().plugins, legend: { display: false } } },
  }));

  // 3) Running Balance — area chart
  const balCtx = document.getElementById("chart-balance").getContext("2d");
  const balGradient = balCtx.createLinearGradient(0, 0, 0, 250);
  balGradient.addColorStop(0, "rgba(210, 168, 255, 0.3)");
  balGradient.addColorStop(1, "rgba(210, 168, 255, 0.0)");
  statsCharts.push(new Chart(balCtx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Balance",
        data: tl.map(d => d.balance),
        borderColor: CHART_COLORS.balance,
        backgroundColor: balGradient,
        fill: true,
        tension: 0.3,
        pointRadius: tl.length > 60 ? 0 : 3,
        pointHoverRadius: 5,
      }],
    },
    options: { ...chartDefaults(), plugins: { ...chartDefaults().plugins, legend: { display: false } } },
  }));

  // 4) Income by Category — doughnut
  const incCats = data.income_by_category || {};
  statsCharts.push(new Chart(document.getElementById("chart-income-cat"), {
    type: "doughnut",
    data: {
      labels: Object.keys(incCats),
      datasets: [{
        data: Object.values(incCats),
        backgroundColor: CHART_COLORS.palette,
        borderColor: "#0d1117",
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "right", labels: { color: CHART_COLORS.text, font: { size: 10 }, padding: 8 } },
        tooltip: chartDefaults().plugins.tooltip,
      },
    },
  }));

  // 5) Expenses by Category — doughnut
  const expCats = data.expense_by_category || {};
  statsCharts.push(new Chart(document.getElementById("chart-expense-cat"), {
    type: "doughnut",
    data: {
      labels: Object.keys(expCats),
      datasets: [{
        data: Object.values(expCats),
        backgroundColor: CHART_COLORS.palette.slice().reverse(),
        borderColor: "#0d1117",
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "right", labels: { color: CHART_COLORS.text, font: { size: 10 }, padding: 8 } },
        tooltip: chartDefaults().plugins.tooltip,
      },
    },
  }));

  // 6) Activity Breakdown — horizontal bar
  const actData = data.activity_breakdown || {};
  const actLabels = Object.keys(actData);
  statsCharts.push(new Chart(document.getElementById("chart-activity"), {
    type: "bar",
    data: {
      labels: actLabels.map(a => a.charAt(0).toUpperCase() + a.slice(1).replace(/_/g, " ")),
      datasets: [
        { label: "Income", data: actLabels.map(a => actData[a].income), backgroundColor: CHART_COLORS.income + "cc" },
        { label: "Expenses", data: actLabels.map(a => actData[a].expenses), backgroundColor: CHART_COLORS.expense + "cc" },
      ],
    },
    options: {
      ...chartDefaults(),
      indexAxis: "y",
      plugins: { ...chartDefaults().plugins, legend: { display: true, labels: { color: CHART_COLORS.text } } },
    },
  }));

  // 7) Top Commodities — horizontal bar
  const comms = data.top_commodities || [];
  statsCharts.push(new Chart(document.getElementById("chart-commodities"), {
    type: "bar",
    data: {
      labels: comms.map(c => c.name),
      datasets: [{
        label: "Net Profit",
        data: comms.map(c => c.profit),
        backgroundColor: comms.map(c => c.profit >= 0 ? CHART_COLORS.income + "cc" : CHART_COLORS.expense + "cc"),
        borderColor: comms.map(c => c.profit >= 0 ? CHART_COLORS.income : CHART_COLORS.expense),
        borderWidth: 1,
      }],
    },
    options: {
      ...chartDefaults(),
      indexAxis: "y",
      plugins: { ...chartDefaults().plugins, legend: { display: false } },
    },
  }));
}

// --- Table Filters ---

function buildFilterRow(cols, extraCols) {
  let cells = cols.map(c => `<th><input type="text" class="col-filter" data-col="${c}" placeholder="Filter..."></th>`).join("");
  for (let i = 0; i < (extraCols || 0); i++) cells += "<th></th>";
  return `<tr class="filter-row">${cells}</tr>`;
}

function wireTableFilters(tableId, container) {
  const el = container || document;
  el.querySelectorAll(`#${tableId} .col-filter`).forEach((input) => {
    input.addEventListener("input", () => {
      const filters = {};
      el.querySelectorAll(`#${tableId} .col-filter`).forEach((f) => {
        const val = f.value.trim().toLowerCase();
        if (val) filters[f.dataset.col] = val;
      });
      el.querySelectorAll(`#${tableId} tbody tr`).forEach((row) => {
        let visible = true;
        for (const [col, term] of Object.entries(filters)) {
          const cellVal = (row.dataset[col] || "").toLowerCase();
          if (!cellVal.includes(term)) { visible = false; break; }
        }
        row.style.display = visible ? "" : "none";
      });
    });
  });
}

// --- UI Helpers ---

function showEmpty(message) {
  document.getElementById("content").innerHTML =
    `<div class="empty-state"><div class="icon">--</div><div>${message}</div></div>`;
}

function summaryCard(label, value, sub, colorClass) {
  const cls = colorClass ? ` ${colorClass}` : "";
  return `<div class="summary-card">
    <div class="label">${label}</div>
    <div class="value${cls}">${value}</div>
    ${sub ? `<div class="sub">${sub}</div>` : ""}
  </div>`;
}

function statementRow(label, value, extra, indent, isTotal) {
  const cls = [];
  if (indent) cls.push("indent");
  if (isTotal) cls.push("total");
  return `<div class="statement-row ${cls.join(" ")}">
    <span class="label">${label}</span>
    <span class="value">${value}${extra ? ` <small style="color:var(--text-muted)">${extra}</small>` : ""}</span>
  </div>`;
}

function renderPagination(page, totalPages) {
  return `<div class="pagination">
    <button class="prev-btn" ${page <= 0 ? "disabled" : ""}>Prev</button>
    <span class="page-info">Page ${page + 1} of ${totalPages}</span>
    <button class="next-btn" ${page + 1 >= totalPages ? "disabled" : ""}>Next</button>
  </div>`;
}

function setupPagination() {
  const prev = document.querySelector(".prev-btn");
  const next = document.querySelector(".next-btn");
  if (prev) {
    prev.addEventListener("click", () => {
      if (currentPage > 0) { currentPage--; loadTab(currentTab); }
    });
  }
  if (next) {
    next.addEventListener("click", () => {
      currentPage++;
      loadTab(currentTab);
    });
  }
}

// --- Modal System ---

let _modalSubmitHandler = null;

function setupModal() {
  const overlay = document.getElementById("modal-overlay");
  const closeBtn = document.getElementById("modal-close");
  const cancelBtn = document.getElementById("modal-cancel");
  const form = document.getElementById("modal-form");

  closeBtn.addEventListener("click", closeModal);
  cancelBtn.addEventListener("click", closeModal);

  // Close on overlay click (but not modal body)
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });

  // Close on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.style.display !== "none") {
      closeModal();
    }
  });

  // Form submit
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (_modalSubmitHandler) _modalSubmitHandler();
  });
}

function openModal(title, bodyHtml, onSubmit) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = bodyHtml;
  document.getElementById("modal-status").textContent = "";
  document.getElementById("modal-status").className = "modal-status";
  document.getElementById("modal-overlay").style.display = "flex";
  _modalSubmitHandler = onSubmit;

  // Focus first input
  const firstInput = document.querySelector("#modal-body input, #modal-body select");
  if (firstInput) setTimeout(() => firstInput.focus(), 50);
}

function closeModal() {
  document.getElementById("modal-overlay").style.display = "none";
  _modalSubmitHandler = null;
}

function showModalSuccess(msg) {
  const status = document.getElementById("modal-status");
  status.textContent = msg;
  status.className = "modal-status success";
  setTimeout(() => {
    closeModal();
    loadBalance();
    loadTab(currentTab);
  }, 800);
}

function showModalError(msg) {
  const status = document.getElementById("modal-status");
  status.textContent = msg;
  status.className = "modal-status error";
}

async function postJSON(url, data) {
  const res = await fetch(API + url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

async function putJSON(url, data) {
  const res = await fetch(API + url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

// --- Category Cache ---

async function loadCategories() {
  cachedCategories = await fetchJSON("/api/categories");
}

function buildCategoryOptions() {
  if (!cachedCategories) return '<option value="">Loading...</option>';
  let html = '<option value="">-- Select --</option>';
  const income = cachedCategories.filter((c) => c.type === "income");
  const expense = cachedCategories.filter((c) => c.type === "expense");

  html += '<optgroup label="Income">';
  for (const c of income) html += `<option value="${c.value}">${escHtml(c.label)}</option>`;
  html += "</optgroup>";

  html += '<optgroup label="Expense">';
  for (const c of expense) html += `<option value="${c.value}">${escHtml(c.label)}</option>`;
  html += "</optgroup>";

  return html;
}

// --- Form Functions ---

function openTransactionForm() {
  const body = `
    <div class="form-group">
      <label>Category</label>
      <select id="f-category" required>${buildCategoryOptions()}</select>
    </div>
    <div class="form-group">
      <label>Amount (aUEC)</label>
      <input id="f-amount" type="number" min="1" step="1" required>
    </div>
    <div class="form-group">
      <label>Description</label>
      <input id="f-description" type="text" required>
    </div>
    <div class="form-group">
      <label>Location</label>
      <input id="f-location" type="text" placeholder="Optional">
    </div>
    <div class="form-group">
      <label>Tags</label>
      <input id="f-tags" type="text" placeholder="Comma-separated, optional">
    </div>`;

  openModal("Add Transaction", body, async () => {
    try {
      await postJSON("/api/transactions", {
        category: document.getElementById("f-category").value,
        amount: parseFloat(document.getElementById("f-amount").value),
        description: document.getElementById("f-description").value,
        location: document.getElementById("f-location").value,
        tags: document.getElementById("f-tags").value,
      });
      showModalSuccess("Transaction recorded");
    } catch (err) {
      showModalError(err.message);
    }
  });
}

function openAssetForm() {
  const body = `
    <div class="form-group">
      <label>Asset Type</label>
      <select id="f-asset-type" required>
        <option value="">-- Select --</option>
        <option value="ship">Ship</option>
        <option value="vehicle">Vehicle</option>
        <option value="component">Component</option>
        <option value="equipment">Equipment</option>
        <option value="blueprint">Blueprint</option>
      </select>
    </div>
    <div class="form-group">
      <label>Name</label>
      <input id="f-name" type="text" required placeholder="e.g. My Cutlass Black">
    </div>
    <div class="form-group">
      <label>Purchase Price (aUEC)</label>
      <input id="f-purchase-price" type="number" min="0" step="1" value="0">
    </div>
    <div class="form-group">
      <label>Ship Model</label>
      <input id="f-ship-model" type="text" placeholder="Optional, e.g. Cutlass Black">
    </div>
    <div class="form-group">
      <label>Location</label>
      <input id="f-asset-location" type="text" placeholder="Optional">
    </div>
    <div class="form-group">
      <label>Notes</label>
      <textarea id="f-notes" rows="2" placeholder="Optional"></textarea>
    </div>`;

  openModal("Add Asset", body, async () => {
    try {
      await postJSON("/api/fleet", {
        asset_type: document.getElementById("f-asset-type").value,
        name: document.getElementById("f-name").value,
        purchase_price: parseFloat(document.getElementById("f-purchase-price").value) || 0,
        ship_model: document.getElementById("f-ship-model").value,
        location: document.getElementById("f-asset-location").value,
        notes: document.getElementById("f-notes").value,
      });
      showModalSuccess("Asset registered");
    } catch (err) {
      showModalError(err.message);
    }
  });
}

function openBalanceForm() {
  const body = `
    <div class="form-group">
      <label>Current Balance (aUEC)</label>
      <input id="f-balance" type="number" step="1" required>
      <div class="hint">This will overwrite the current balance. Use this to correct or initialize your aUEC amount.</div>
    </div>`;

  openModal("Set Balance", body, async () => {
    try {
      await postJSON("/api/balance", {
        amount: parseFloat(document.getElementById("f-balance").value),
      });
      showModalSuccess("Balance updated");
    } catch (err) {
      showModalError(err.message);
    }
  });
}

function openPurchaseForm() {
  const body = `
    <div class="form-group">
      <label>Commodity Name</label>
      <input id="f-commodity" type="text" required placeholder="e.g. Laranite">
    </div>
    <div class="form-group">
      <label>Quantity (SCU)</label>
      <input id="f-quantity" type="number" min="0.01" step="0.01" required>
    </div>
    <div class="form-group">
      <label>Price per SCU (aUEC)</label>
      <input id="f-price" type="number" min="0.01" step="0.01" required>
    </div>
    <div class="form-group">
      <label>Location</label>
      <input id="f-pos-location" type="text" placeholder="Optional">
    </div>`;

  openModal("Record Purchase", body, async () => {
    try {
      await postJSON("/api/positions", {
        commodity_name: document.getElementById("f-commodity").value,
        quantity_scu: parseFloat(document.getElementById("f-quantity").value),
        price_per_scu: parseFloat(document.getElementById("f-price").value),
        location: document.getElementById("f-pos-location").value,
      });
      showModalSuccess("Purchase recorded");
    } catch (err) {
      showModalError(err.message);
    }
  });
}

function openEditTransactionForm(txn) {
  const body = `
    <div class="form-group">
      <label>Category</label>
      <select id="f-category" required>${buildCategoryOptions()}</select>
    </div>
    <div class="form-group">
      <label>Amount (aUEC)</label>
      <input id="f-amount" type="number" min="1" step="1" required>
    </div>
    <div class="form-group">
      <label>Description</label>
      <input id="f-description" type="text" required>
    </div>
    <div class="form-group">
      <label>Location</label>
      <input id="f-location" type="text" placeholder="Optional">
    </div>
    <div class="form-group">
      <label>Tags</label>
      <input id="f-tags" type="text" placeholder="Comma-separated, optional">
    </div>
    <hr>
    <div class="form-group">
      <button type="button" id="f-delete-txn" class="btn-danger">Delete Transaction</button>
    </div>`;

  openModal("Edit Transaction", body, async () => {
    try {
      await putJSON(`/api/transactions/${txn.id}`, {
        category: document.getElementById("f-category").value,
        amount: parseFloat(document.getElementById("f-amount").value),
        description: document.getElementById("f-description").value,
        location: document.getElementById("f-location").value,
        tags: document.getElementById("f-tags").value,
      });
      showModalSuccess("Transaction updated");
    } catch (err) {
      showModalError(err.message);
    }
  });

  // Pre-fill after modal is open
  document.getElementById("f-category").value = txn.category;
  document.getElementById("f-amount").value = txn.amount;
  document.getElementById("f-description").value = txn.description;
  document.getElementById("f-location").value = txn.location || "";
  document.getElementById("f-tags").value = (txn.tags || []).join(", ");

  // Wire delete button
  document.getElementById("f-delete-txn").addEventListener("click", async () => {
    if (!confirm(`Delete this transaction?\n\n${txn.description}\n${txn.amount} aUEC`)) return;
    try {
      const res = await fetch(`/api/transactions/${txn.id}`, {method: "DELETE"});
      if (!res.ok) {
        const err = await res.json();
        showModalError(err.error || "Delete failed");
        return;
      }
      showModalSuccess("Transaction deleted");
    } catch (err) {
      showModalError(err.message);
    }
  });
}

function openEditAssetForm(asset) {
  const body = `
    <div class="form-group">
      <label>Asset Type</label>
      <select id="f-asset-type" required>
        <option value="ship">Ship</option>
        <option value="vehicle">Vehicle</option>
        <option value="component">Component</option>
        <option value="equipment">Equipment</option>
        <option value="blueprint">Blueprint</option>
      </select>
    </div>
    <div class="form-group">
      <label>Name</label>
      <input id="f-name" type="text" required>
    </div>
    <div class="form-group">
      <label>Purchase Price (aUEC)</label>
      <input id="f-purchase-price" type="number" min="0" step="1">
    </div>
    <div class="form-group">
      <label>Ship Model</label>
      <input id="f-ship-model" type="text" placeholder="Optional">
    </div>
    <div class="form-group">
      <label>Location</label>
      <input id="f-asset-location" type="text" placeholder="Optional">
    </div>
    <div class="form-group">
      <label>Notes</label>
      <textarea id="f-notes" rows="2" placeholder="Optional"></textarea>
    </div>`;

  openModal("Edit Asset", body, async () => {
    try {
      await putJSON(`/api/fleet/${asset.id}`, {
        asset_type: document.getElementById("f-asset-type").value,
        name: document.getElementById("f-name").value,
        purchase_price: parseFloat(document.getElementById("f-purchase-price").value) || 0,
        ship_model: document.getElementById("f-ship-model").value,
        location: document.getElementById("f-asset-location").value,
        notes: document.getElementById("f-notes").value,
      });
      showModalSuccess("Asset updated");
    } catch (err) {
      showModalError(err.message);
    }
  });

  // Pre-fill after modal is open
  document.getElementById("f-asset-type").value = asset.asset_type;
  document.getElementById("f-name").value = asset.name;
  document.getElementById("f-purchase-price").value = asset.purchase_price || 0;
  document.getElementById("f-ship-model").value = asset.ship_model || "";
  document.getElementById("f-asset-location").value = asset.location || "";
  document.getElementById("f-notes").value = asset.notes || "";

  // Add delete button to modal footer
  const modalActions = document.querySelector(".modal-actions");
  if (modalActions) {
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "btn-danger";
    deleteBtn.textContent = "Delete Asset";
    deleteBtn.addEventListener("click", async () => {
      if (!confirm(`Delete "${asset.name}"? This cannot be undone.`)) return;
      try {
        const resp = await fetch(`/api/fleet/${asset.id}`, {method: "DELETE"});
        if (!resp.ok) {
          const err = await resp.json();
          showModalError(err.error || "Delete failed");
          return;
        }
        closeModal();
        renderFleet();
      } catch (err) {
        showModalError(err.message);
      }
    });
    modalActions.insertBefore(deleteBtn, modalActions.firstChild);
  }
}

function openEditPositionForm(pos) {
  const body = `
    <div class="form-group">
      <label>Commodity Name</label>
      <input id="f-pos-name" type="text" required>
    </div>
    <div class="form-group">
      <label>Quantity (SCU)</label>
      <input id="f-pos-qty" type="number" min="0.01" step="0.01" required>
    </div>
    <div class="form-group">
      <label>Comment</label>
      <textarea id="f-pos-notes" rows="2" placeholder="Optional"></textarea>
    </div>`;

  openModal("Edit Position", body, async () => {
    try {
      await putJSON(`/api/positions/${pos.id}`, {
        commodity_name: document.getElementById("f-pos-name").value,
        quantity: parseFloat(document.getElementById("f-pos-qty").value),
        notes: document.getElementById("f-pos-notes").value,
      });
      showModalSuccess("Position updated");
    } catch (err) {
      showModalError(err.message);
    }
  });

  document.getElementById("f-pos-name").value = pos.commodity_name || "";
  document.getElementById("f-pos-qty").value = pos.quantity || 0;
  document.getElementById("f-pos-notes").value = pos.notes || "";
}

function openSaleForm() {
  const body = `
    <div class="form-group">
      <label>Commodity Name</label>
      <input id="f-sale-commodity" type="text" required placeholder="e.g. Laranite">
    </div>
    <div class="form-group">
      <label>Quantity (SCU)</label>
      <input id="f-sale-quantity" type="number" min="0.01" step="0.01" required>
    </div>
    <div class="form-group">
      <label>Sale Price per SCU (aUEC)</label>
      <input id="f-sale-price" type="number" min="0.01" step="0.01" required>
    </div>
    <div class="form-group">
      <label>Location</label>
      <input id="f-sale-location" type="text" placeholder="Optional">
    </div>`;

  openModal("Record Sale", body, async () => {
    try {
      await postJSON("/api/sales", {
        commodity_name: document.getElementById("f-sale-commodity").value,
        quantity_scu: parseFloat(document.getElementById("f-sale-quantity").value),
        price_per_scu: parseFloat(document.getElementById("f-sale-price").value),
        location: document.getElementById("f-sale-location").value,
      });
      showModalSuccess("Sale recorded");
    } catch (err) {
      showModalError(err.message);
    }
  });
}

// --- Action Bar Helper ---

// --- Group Session Tab ---


function formatAuec(value) {
  const abs = Math.abs(value);
  let formatted;
  if (abs >= 1000000) {
    formatted = (abs / 1000000).toFixed(2) + "M";
  } else if (abs >= 1000) {
    formatted = (abs / 1000).toFixed(1) + "K";
  } else {
    formatted = abs.toFixed(0);
  }
  return (value < 0 ? "-" : "") + formatted + " aUEC";
}

function formatTimestamp(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const da = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${y}:${mo}:${da} - ${h}:${mi}`;
}

// --- Utility Functions ---

function actionBar(...labels) {
  let html = '<div class="tab-action-bar">';
  for (let i = 0; i < labels.length; i++) {
    html += `<button class="btn-add" id="tab-add-btn-${i}">${escHtml(labels[i])}</button>`;
  }
  html += "</div>";
  return html;
}

function wireActionButton(onClick, index) {
  const idx = index != null ? index : 0;
  const btn = document.getElementById(`tab-add-btn-${idx}`);
  if (btn) btn.addEventListener("click", onClick);
}

function escHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
