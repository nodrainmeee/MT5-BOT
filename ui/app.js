/* =====================================================================
   app.js : comportement de l'interface MonBot.
   - Parle au Python via window.pywebview.api.<méthode>() (asynchrone).
   - Interroge l'état du bot une fois par seconde (get_state).
   - Dessine la courbe du jour sur un <canvas> (aucune bibliothèque externe).
   ===================================================================== */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const app = {
  lastLogId: 0,
  running: false,
  starting: false,
  currency: "",
  confirmText: "JE COMPRENDS LES RISQUES",
  curve: [],
  lastTradesRefresh: 0,
};

/* ---------------------------------------------------------------------
   Appel sécurisé d'une méthode Python
   --------------------------------------------------------------------- */
async function call(nom, ...args) {
  if (!window.pywebview || !window.pywebview.api) {
    toast("Fonction disponible uniquement dans le logiciel", "error");
    throw new Error("pywebview indisponible");
  }
  try {
    return await window.pywebview.api[nom](...args);
  } catch (err) {
    toast("Erreur : " + (err && err.message ? err.message : err), "error");
    throw err;
  }
}

/* ---------------------------------------------------------------------
   Petites aides d'affichage
   --------------------------------------------------------------------- */
const fmt = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
function money(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return fmt.format(v) + (app.currency ? " " + app.currency : "");
}
function signed(v) { return (v > 0 ? "+" : "") + fmt.format(v); }

let toastTimer = null;
function toast(message, type = "") {
  const t = $("#toast");
  t.textContent = message;
  t.className = "toast show " + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = "toast " + type; }, 3500);
}

function setPill(id, state, texte) {
  const el = document.getElementById(id);
  el.dataset.state = state;
  el.querySelector(".pill-v").textContent = texte;
}

/* ---------------------------------------------------------------------
   Thème clair / sombre
   --------------------------------------------------------------------- */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = $("#theme-toggle");
  const sombre = theme === "dark";
  btn.setAttribute("aria-checked", String(sombre));
  btn.setAttribute("aria-label", sombre ? "Thème sombre activé" : "Thème clair activé");
  try { localStorage.setItem("monbot-theme", theme); } catch (e) { /* ignoré */ }
  drawChart();
}
function toggleTheme() {
  const nouveau = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(nouveau);
  if (window.pywebview && window.pywebview.api) call("set_theme", nouveau).catch(() => {});
}

/* ---------------------------------------------------------------------
   Formulaire des réglages
   --------------------------------------------------------------------- */
function fillSettings(s) {
  $$("#settings-form [data-key]").forEach((el) => {
    const v = s[el.dataset.key];
    if (v === undefined) return;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = String(v);
  });
  $$("#assets input[data-symbol]").forEach((cb) => { cb.checked = !!s.symbols[cb.dataset.symbol]; });
  $("#xau-warning").hidden = !s.symbols.XAUUSD;
  $("#news-minutes").value = String(s.news_pause_min || 30);
  $("#mt5-login").value = s.mt5_login || "";
  $("#mt5-server").value = s.mt5_server || "";
  $("#mt5-remember").checked = !!s.remember_credentials;
  $("#stat-trades-max").textContent = "sur " + s.max_trades_per_day + " maximum";
  updateMode(s.real_mode_enabled);
}

/* Vérifie les champs AVANT l'envoi et affiche l'erreur sous le champ */
function readSettings() {
  let ok = true;
  const data = {};
  $$("#settings-form [data-key]").forEach((el) => {
    const err = el.parentElement.querySelector(".field-error");
    el.removeAttribute("aria-invalid");
    if (err) err.textContent = "";
    if (el.type === "checkbox") {
      data[el.dataset.key] = el.checked;
    } else if (el.type === "number") {
      const v = Number(el.value);
      const min = Number(el.min), max = Number(el.max);
      if (el.value === "" || Number.isNaN(v) || v < min || v > max) {
        ok = false;
        el.setAttribute("aria-invalid", "true");
        if (err) err.textContent = `Entrez une valeur entre ${min} et ${max}.`;
        return;
      }
      data[el.dataset.key] = v;
    } else if (el.dataset.key === "trend_ema") {
      data[el.dataset.key] = Number(el.value);
    } else {
      data[el.dataset.key] = el.value;
    }
  });
  data.symbols = {};
  $$("#assets input[data-symbol]").forEach((cb) => { data.symbols[cb.dataset.symbol] = cb.checked; });
  data.news_pause_min = Number($("#news-minutes").value);
  if (!Object.values(data.symbols).some(Boolean)) {
    ok = false;
    toast("Cochez au moins un actif", "error");
  }
  return ok ? data : null;
}

async function saveSettings() {
  const data = readSettings();
  if (!data) { const bad = $("[aria-invalid='true']"); if (bad) bad.focus(); return; }
  const btn = $("#btn-save");
  btn.disabled = true;
  try {
    const res = await call("save_settings", data);
    fillSettings(res.settings);
    toast(res.notes.length ? "Enregistré avec corrections (voir journal)" : "Réglages enregistrés", "success");
  } finally { btn.disabled = false; }
}

/* ---------------------------------------------------------------------
   Mode démo / réel
   --------------------------------------------------------------------- */
function updateMode(reel) {
  const badge = $("#mode-badge");
  badge.dataset.mode = reel ? "real" : "demo";
  badge.querySelector("span").textContent = reel ? "Mode RÉEL autorisé" : "Mode DÉMO";
  $("#btn-real").textContent = reel ? "Revenir en mode démo" : "Passer en mode réel";
  $("#mode-help").textContent = reel
    ? "Le bot peut trader sur un compte réel. Les limites de risque restent actives."
    : "En mode démo, le bot refuse de trader sur un compte réel.";
  app.realMode = reel;
}

async function onRealButton() {
  if (app.realMode) {
    await call("disable_real_mode");
    updateMode(false);
    toast("Retour au mode démo", "success");
    return;
  }
  if (app.running) { toast("Arrêtez d'abord le bot", "error"); return; }
  $("#real-confirm").value = "";
  $("#real-error").textContent = "";
  $("#real-ok").disabled = true;
  $("#modal-real").showModal();
  $("#real-confirm").focus();
}

async function confirmReal() {
  const res = await call("enable_real_mode", $("#real-confirm").value);
  if (!res.ok) { $("#real-error").textContent = res.message; return; }
  $("#modal-real").close();
  updateMode(true);
  toast("Mode réel activé : prudence", "error");
}

/* ---------------------------------------------------------------------
   Commandes du bot
   --------------------------------------------------------------------- */
async function startBot() {
  const login = $("#mt5-login").value.trim();
  const errLogin = $("#err-login");
  errLogin.textContent = "";
  $("#mt5-login").removeAttribute("aria-invalid");
  if (login && !/^\d+$/.test(login)) {
    errLogin.textContent = "Le numéro de compte ne contient que des chiffres.";
    $("#mt5-login").setAttribute("aria-invalid", "true");
    $("#mt5-login").focus();
    return;
  }
  // On enregistre d'abord les réglages affichés (actifs cochés, etc.)
  const data = readSettings();
  if (!data) return;
  await call("save_settings", data);

  const btn = $("#btn-start");
  btn.disabled = true;
  btn.lastChild.textContent = "Connexion...";
  const res = await call("start_bot", {
    login, password: $("#mt5-password").value, server: $("#mt5-server").value.trim(),
    remember: $("#mt5-remember").checked,
  });
  $("#mt5-password").value = "";          // on ne garde pas le mot de passe affiché
  if (!res.ok) { toast(res.message, "error"); btn.disabled = false; }
  btn.lastChild.textContent = "Démarrer";
}

async function stopBot() { await call("stop_bot"); toast("Bot arrêté"); }

async function emergencyStop() {
  const res = await call("emergency_stop");
  const n = res.open_positions || 0;
  if (n > 0) {
    $("#em-text").textContent = `Le bot est arrêté. ${n} position(s) ouverte(s) par le bot sont encore en cours (avec leur stop loss). Voulez-vous les fermer maintenant au prix du marché ?`;
    $("#modal-emergency").showModal();
  } else {
    toast("Bot arrêté. Aucune position du bot n'est ouverte.", "success");
  }
}

async function closeAll() {
  const btn = $("#em-close");
  btn.disabled = true;
  try {
    const res = await call("close_all_positions");
    toast(res.message, res.failed ? "error" : "success");
  } finally { btn.disabled = false; $("#modal-emergency").close(); }
}

/* ---------------------------------------------------------------------
   Rafraîchissement de l'état (toutes les secondes)
   --------------------------------------------------------------------- */
async function poll() {
  try {
    const s = await window.pywebview.api.get_state(app.lastLogId);
    render(s);
  } catch (e) { /* une erreur ponctuelle ne doit pas arrêter la boucle */ }
  setTimeout(poll, 1000);
}

function render(s) {
  app.running = s.running;
  app.starting = s.starting;
  app.currency = s.currency || "";

  // Témoins
  setPill("pill-mt5", s.connected ? "ok" : (s.running ? "danger" : "off"), s.connected ? "Connecté" : "Non connecté");
  if (s.connected) setPill("pill-algo", s.algo_trading ? "ok" : "danger", s.algo_trading ? "Actif" : "Désactivé");
  else setPill("pill-algo", "off", "Inconnu");
  const modes = { demo: ["ok", "DÉMO"], real: ["danger", "RÉEL"], contest: ["warn", "Concours"] };
  const m = modes[s.account_mode];
  setPill("pill-account", m ? m[0] : "off", m ? m[1] + (s.login ? " · " + s.login : "") : "—");
  if (s.starting) setPill("pill-bot", "warn", "Démarrage...");
  else setPill("pill-bot", s.running ? "ok" : "off", s.running ? "Actif" : "Arrêté");

  // Boutons
  $("#btn-start").disabled = s.running || s.starting;
  $("#btn-stop").disabled = !(s.running || s.starting);
  $("#btn-real").disabled = s.running && !s.real_mode_enabled;

  // Chiffres
  $("#stat-balance").textContent = money(s.balance);
  $("#stat-equity").textContent = money(s.equity);
  $("#stat-currency").textContent = s.currency ? "Devise : " + s.currency : "\u00a0";
  $("#stat-positions").textContent = (s.open_positions || 0) + " position(s) ouverte(s)";
  const pnl = $("#stat-pnl"), pct = $("#stat-pnl-pct");
  pnl.textContent = s.balance === null ? "—" : signed(s.daily_pnl) + (app.currency ? " " + app.currency : "");
  pct.textContent = s.balance === null ? "\u00a0" : signed(s.daily_pnl_pct) + " %";
  const cls = s.daily_pnl > 0 ? "pos" : (s.daily_pnl < 0 ? "neg" : "");
  pnl.className = "stat-v " + cls;
  pct.className = "stat-sub " + cls;
  $("#stat-trades").textContent = s.trades_today;
  $("#stat-trades-max").textContent = "sur " + s.max_trades + " maximum";

  // Bandeaux
  const pause = $("#pause-banner");
  pause.hidden = !s.pause_message;
  pause.textContent = s.pause_message || "";
  const halt = $("#halt-banner");
  halt.hidden = !s.halt_message;
  halt.textContent = s.halt_message ? s.halt_message + ". Le bot est arrêté pour aujourd'hui." : "";

  // Journal
  if (s.logs && s.logs.length) {
    appendLogs(s.logs);
    app.lastLogId = s.logs[s.logs.length - 1].id;
    if (s.logs.some((l) => /fermée|exécuté|ACHAT|VENTE/.test(l.message))) refreshTrades();
  }

  // Courbe
  if (JSON.stringify(s.pnl_curve) !== JSON.stringify(app.curve)) {
    app.curve = s.pnl_curve || [];
    drawChart();
  }
  if (Date.now() - app.lastTradesRefresh > 30000) refreshTrades();
}

const LIBELLES = { info: "Info", success: "OK", warning: "Attention", error: "Erreur", signal: "Signal" };
function appendLogs(lignes) {
  const liste = $("#log-list");
  const frag = document.createDocumentFragment();
  for (const l of lignes) {
    const li = document.createElement("li");
    li.className = "lv-" + l.level;
    // textContent (et non innerHTML) : aucun risque d'injection de code
    const t = document.createElement("span"); t.className = "log-time"; t.textContent = l.time;
    const b = document.createElement("span"); b.className = "log-badge"; b.textContent = LIBELLES[l.level] || l.level;
    const msg = document.createElement("span"); msg.className = "log-msg"; msg.textContent = l.message;
    li.append(t, b, msg);
    frag.appendChild(li);
  }
  liste.appendChild(frag);
  while (liste.children.length > 400) liste.removeChild(liste.firstChild);
  if ($("#log-autoscroll").checked) liste.scrollTop = liste.scrollHeight;
}

async function refreshTrades() {
  app.lastTradesRefresh = Date.now();
  let rows;
  try { rows = await window.pywebview.api.get_trades(); } catch (e) { return; }
  const body = $("#trades-body");
  body.textContent = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td"); td.colSpan = 7; td.className = "muted";
    td.textContent = "Aucun trade pour l'instant."; tr.appendChild(td); body.appendChild(tr);
    return;
  }
  for (const r of rows) {
    const tr = document.createElement("tr");
    const cells = [
      (r.ts_open || "").replace("T", " ").slice(5, 16), r.symbol,
      r.direction === "BUY" ? "Achat" : "Vente", r.volume, r.signal || "",
      r.close_reason || "en cours",
      r.profit === null || r.profit === undefined ? "—" : signed(r.profit),
    ];
    cells.forEach((c, i) => {
      const td = document.createElement("td");
      td.textContent = c;
      if (i === 3 || i === 6) td.className = "num";
      if (i === 6 && r.profit) td.classList.add(r.profit > 0 ? "pos" : "neg");
      tr.appendChild(td);
    });
    body.appendChild(tr);
  }
}

/* ---------------------------------------------------------------------
   Graphique du résultat du jour (canvas)
   --------------------------------------------------------------------- */
function cssVar(nom) { return getComputedStyle(document.documentElement).getPropertyValue(nom).trim(); }

function drawChart() {
  const canvas = $("#pnl-chart");
  if (!canvas) return;
  const pts = app.curve;
  $("#chart-empty").hidden = pts.length >= 2;
  const ratio = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = Math.round(w * ratio);
  canvas.height = Math.round(h * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (pts.length < 2) return;

  const pad = { l: 56, r: 12, t: 12, b: 24 };
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys);
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const marge = (y1 - y0) * 0.12; y0 -= marge; y1 += marge;
  const X = (x) => pad.l + ((x - x0) / Math.max(1, x1 - x0)) * (w - pad.l - pad.r);
  const Y = (y) => pad.t + (1 - (y - y0) / (y1 - y0)) * (h - pad.t - pad.b);

  const muted = cssVar("--muted"), border = cssVar("--glass-border");
  const dernier = ys[ys.length - 1];
  const couleur = dernier >= 0 ? cssVar("--success") : cssVar("--danger");

  // Ligne du zéro + étiquettes
  ctx.strokeStyle = border; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(pad.l, Y(0)); ctx.lineTo(w - pad.r, Y(0)); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = muted; ctx.font = "12px " + cssVar("--font");
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  [y1 - marge, 0, y0 + marge].forEach((v) => ctx.fillText(fmt.format(v), pad.l - 8, Y(v)));
  ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
  const heure = (t) => new Date(t * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  ctx.fillText(heure(x0), pad.l, h - 6);
  ctx.textAlign = "right"; ctx.fillText(heure(x1), w - pad.r, h - 6);

  // Remplissage dégradé sous la courbe
  const grad = ctx.createLinearGradient(0, pad.t, 0, h - pad.b);
  grad.addColorStop(0, couleur + "55"); grad.addColorStop(1, couleur + "00");
  ctx.beginPath(); ctx.moveTo(X(xs[0]), Y(0));
  pts.forEach((p) => ctx.lineTo(X(p[0]), Y(p[1])));
  ctx.lineTo(X(xs[xs.length - 1]), Y(0)); ctx.closePath();
  ctx.fillStyle = couleur.startsWith("#") && couleur.length === 7 ? grad : "transparent";
  ctx.fill();

  // Courbe
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1]))));
  ctx.strokeStyle = couleur; ctx.lineWidth = 2.2; ctx.lineJoin = "round"; ctx.stroke();

  canvas.setAttribute("aria-label", `Courbe du résultat du jour : ${signed(dernier)} ${app.currency}`);
}

/* ---------------------------------------------------------------------
   Démarrage de l'interface
   --------------------------------------------------------------------- */
function bindEvents() {
  $("#theme-toggle").addEventListener("click", toggleTheme);
  $("#btn-save").addEventListener("click", saveSettings);
  $("#btn-start").addEventListener("click", startBot);
  $("#btn-stop").addEventListener("click", stopBot);
  $("#btn-emergency").addEventListener("click", emergencyStop);
  $("#btn-news").addEventListener("click", async () => {
    const r = await call("pause_news", Number($("#news-minutes").value));
    toast(`Pause de ${r.minutes} min activée`);
  });
  $("#btn-resume").addEventListener("click", () => call("resume"));
  $("#btn-folder").addEventListener("click", () => call("open_data_folder"));
  $("#btn-export").addEventListener("click", async () => {
    const r = await call("export_trades_csv");
    toast("Exporté : " + r.path, "success");
  });
  $("#btn-forget").addEventListener("click", async () => {
    await call("forget_credentials");
    $("#mt5-login").value = ""; $("#mt5-server").value = ""; $("#mt5-password").value = "";
    $("#mt5-remember").checked = false; $("#pwd-help").textContent = "";
    toast("Identifiants oubliés", "success");
  });
  $("#btn-real").addEventListener("click", onRealButton);
  $("#real-cancel").addEventListener("click", () => $("#modal-real").close());
  $("#real-ok").addEventListener("click", confirmReal);
  $("#real-confirm").addEventListener("input", (e) => {
    $("#real-ok").disabled = e.target.value.trim().toUpperCase() !== app.confirmText;
  });
  $("#em-keep").addEventListener("click", () => { $("#modal-emergency").close(); toast("Positions conservées (avec leur stop loss)"); });
  $("#em-close").addEventListener("click", closeAll);
  $$("#assets input").forEach((cb) => cb.addEventListener("change", () => {
    $("#xau-warning").hidden = !$("#assets input[data-symbol='XAUUSD']").checked;
  }));
  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawChart, 120); });
}

async function init() {
  const data = await call("get_initial");
  $("#app-version").textContent = "v" + data.version;
  app.confirmText = data.confirm_text;
  $("#real-text").textContent = data.confirm_text;
  applyTheme(data.settings.theme);
  fillSettings(data.settings);
  if (data.has_saved_password) $("#pwd-help").textContent = "Mot de passe mémorisé dans Windows : laissez vide pour l'utiliser.";
  poll();
  refreshTrades();
}

// Thème appliqué tout de suite (évite un "flash" à l'ouverture)
try { const t = localStorage.getItem("monbot-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* ignoré */ }

document.addEventListener("DOMContentLoaded", bindEvents);
// pywebview déclenche cet événement quand le pont Python est prêt
window.addEventListener("pywebviewready", init);
// Aperçu dans un simple navigateur (sans Python) : on le signale
setTimeout(() => { if (!window.pywebview) $("#preview-warning").hidden = false; }, 1500);
