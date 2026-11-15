"use strict";

const $ = (id) => document.getElementById(id);
const fmt = (n) => Math.round(n).toLocaleString("ru-RU");
const rub = (n) => `${fmt(n)} ₽`;
const SVGNS = "http://www.w3.org/2000/svg";

let info = null;          // маршруты и даты из /api/routes
let authMode = "login";
let liveTimer = null;
let lastResult = null;

async function api(path, options = {}) {
  const res = await fetch(path, {
    method: options.body ? "POST" : options.method || "GET",
    headers: options.body ? { "Content-Type": "application/json" } : {},
    body: options.body ? JSON.stringify(options.body) : undefined,
    credentials: "same-origin",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || `Ошибка ${res.status}`), { status: res.status });
  return data;
}

// ---------------- вход и регистрация ----------------
function showAuth() {
  $("authView").hidden = false;
  $("appView").hidden = true;
  $("userBox").hidden = true;
}

function showApp(login) {
  $("authView").hidden = true;
  $("appView").hidden = false;
  $("userBox").hidden = false;
  $("userName").textContent = login;
  loadHistory();
  loadCalendar();
  calculate(false);
}

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    authMode = tab.dataset.mode;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    $("authSubmit").textContent = authMode === "login" ? "Войти" : "Создать аккаунт";
    $("authForm").password.autocomplete = authMode === "login" ? "current-password" : "new-password";
    $("authError").textContent = "";
  }));

$("authForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  $("authError").textContent = "";
  try {
    const me = await api(`/api/${authMode}`, { body: { login: form.login.value, password: form.password.value } });
    form.reset();
    showApp(me.login);
  } catch (err) {
    $("authError").textContent = err.message;
  }
});

$("logoutBtn").addEventListener("click", async () => {
  await api("/api/logout", { body: {} });
  showAuth();
});

// ---------------- форма ----------------
function currentRoute() {
  return info.routes.find((r) => r.destination === $("destination").value);
}

function syncPriceBounds(resetPrice) {
  const r = currentRoute();
  const range = $("priceRange");
  range.min = r.price_min;
  range.max = r.price_max;
  $("pMin").textContent = rub(r.price_min);
  $("pBase").textContent = `базовая ${rub(r.base_price)}`;
  $("pMax").textContent = rub(r.price_max);
  if (resetPrice) $("price").value = r.base_price;
  range.value = $("price").value;
  paintSlider();
}

// фиолетовая заливка бегунка до текущей цены
function paintSlider() {
  const range = $("priceRange");
  const share = (Number(range.value) - Number(range.min)) / (Number(range.max) - Number(range.min) || 1);
  range.style.setProperty("--fill", `${Math.min(100, Math.max(0, share * 100))}%`);
}

function formData(save) {
  return {
    origin: $("origin").value,
    destination: $("destination").value,
    date: $("date").value,
    price: $("price").value,
    save,
  };
}

async function calculate(save) {
  $("fcError").textContent = "";
  try {
    const r = await api("/api/forecast", { body: formData(save) });
    renderResult(r);
    if (save) loadHistory();
  } catch (err) {
    if (err.status === 401) return showAuth();
    $("fcError").textContent = err.message;
    $("result").hidden = true;
  }
}

function scheduleLive() {
  clearTimeout(liveTimer);
  liveTimer = setTimeout(() => calculate(false), 180);
}

$("fcForm").addEventListener("submit", (e) => { e.preventDefault(); calculate(true); });
$("priceRange").addEventListener("input", (e) => { $("price").value = e.target.value; paintSlider(); scheduleLive(); });
$("price").addEventListener("input", () => { $("priceRange").value = $("price").value; paintSlider(); scheduleLive(); });
$("date").addEventListener("change", () => { markSelectedDay(); scheduleLive(); });
$("destination").addEventListener("change", () => { syncPriceBounds(true); loadCalendar(); scheduleLive(); });

document.querySelectorAll("[data-use]").forEach((btn) =>
  btn.addEventListener("click", () => {
    if (!lastResult) return;
    const p = btn.dataset.use === "model" ? lastResult.model_price_median : lastResult.robust_price.price;
    $("price").value = Math.round(p / 100) * 100;
    $("priceRange").value = $("price").value;
    paintSlider();
    calculate(false);
  }));

// ---------------- результат ----------------
function renderResult(r) {
  lastResult = r;
  $("result").hidden = false;
  $("sSeats").textContent = fmt(r.seats);
  $("sWant").textContent = fmt(r.want);
  $("sBuy").textContent = fmt(r.buy);
  $("sLoad").textContent = r.seats ? `заполнено ${Math.round((100 * r.buy) / r.seats)}%` : "";
  $("sSell").textContent = r.sellout_probability.label;
  $("sProfit").textContent = `${(r.expected_profit / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} млн ₽`;
  $("warnings").textContent = r.warnings.join(" ");
  $("chartPrice").textContent = rub(r.price);
  $("aModel").textContent = rub(r.model_price_median);
  $("aModelRange").textContent = `в сценариях 0.1–0.9: ${rub(r.model_price_range[0])} – ${rub(r.model_price_range[1])}`;
  $("aRobust").textContent = rub(r.robust_price.price);
  $("aRobustProfit").textContent = `средняя прибыль ${(r.robust_price.expected_profit / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} млн ₽`;
  const capped = r.scenarios.filter((s) => s.want > r.seats).length;
  $("chartNote").textContent = capped
    ? `В ${capped} из 9 сценариев желающих больше, чем мест: продажи упираются в ${fmt(r.seats)} кресел. Медиана (0.5) совпадает с простым прогнозом: хотят ${fmt(r.want)}.`
    : `Во всех сценариях мест хватает. Медиана (0.5) совпадает с простым прогнозом: хотят ${fmt(r.want)}.`;
  drawChart(r);
}

function el(name, attrs, parent) {
  const node = document.createElementNS(SVGNS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function drawChart(r) {
  const svg = $("chart");
  const W = svg.clientWidth || 800;
  const H = svg.clientHeight || 300;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.replaceChildren();
  const css = getComputedStyle(document.documentElement);
  const color = (v) => css.getPropertyValue(v).trim();

  const pad = { l: 46, r: 12, t: 22, b: 44 };
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;
  const top = Math.max(r.seats, ...r.scenarios.map((s) => s.want), 1) * 1.12;
  const y = (v) => pad.t + ih - (Math.max(0, v) / top) * ih;

  const defs = el("defs", {}, svg);
  const pat = el("pattern", { id: "hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
  el("rect", { width: 6, height: 6, fill: color("--over"), opacity: 0.18 }, pat);
  el("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: color("--over"), "stroke-width": 3 }, pat);

  const step = niceStep(top / 4);
  for (let v = 0; v <= top; v += step) {
    el("line", { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), class: "grid" }, svg);
    el("text", { x: pad.l - 6, y: y(v) + 4, "text-anchor": "end" }, svg).textContent = fmt(v);
  }

  const n = r.scenarios.length;
  const slot = iw / n;
  const bw = Math.min(56, slot * 0.62);
  const names = { "0.1": "пессим.", "0.5": "медиана", "0.9": "оптим." };
  r.scenarios.forEach((s, i) => {
    const cx = pad.l + slot * i + slot / 2;
    const x = cx - bw / 2;
    const sold = Math.min(Math.max(s.want, 0), r.seats);
    const g = el("g", { tabindex: 0 }, svg);
    if (sold > 0) el("rect", { x, y: y(sold), width: bw, height: y(0) - y(sold), rx: 4, fill: color("--sold") }, g);
    if (s.want > r.seats) {
      el("rect", { x, y: y(s.want), width: bw, height: y(r.seats) - y(s.want), fill: "url(#hatch)", stroke: color("--over"), "stroke-width": 1, rx: 4 }, g);
    }
    if (s.quantile === "0.5") {
      el("rect", { x: x - 3, y: y(Math.max(s.want, 0)) - 3, width: bw + 6, height: y(0) - y(Math.max(s.want, 0)) + 3, rx: 6, fill: "none", stroke: color("--text"), "stroke-width": 1.5 }, g);
    }
    if (slot >= 48 || names[s.quantile]) {   // на узком экране подписываем только 0.1, 0.5 и 0.9
      el("text", { x: cx, y: y(Math.max(s.want, 0)) - 7, "text-anchor": "middle", class: "val halo" }, g).textContent = fmt(Math.max(s.want, 0));
    }
    el("text", { x: cx, y: H - pad.b + 16, "text-anchor": "middle" }, svg).textContent = s.quantile;
    if (names[s.quantile]) el("text", { x: cx, y: H - pad.b + 31, "text-anchor": "middle" }, svg).textContent = names[s.quantile];
    const hit = el("rect", { x: pad.l + slot * i, y: pad.t, width: slot, height: ih, fill: "transparent" }, g);
    const show = () => showTip(cx, y(Math.max(s.want, 0)), s, r);
    hit.addEventListener("mouseenter", show);
    g.addEventListener("focus", show);
    hit.addEventListener("mouseleave", hideTip);
    g.addEventListener("blur", hideTip);
  });

  el("line", { x1: pad.l, x2: W - pad.r, y1: y(r.seats), y2: y(r.seats), stroke: color("--seat-line"), "stroke-width": 2, "stroke-dasharray": "6 4" }, svg);
  // число мест подписано в легенде, чтобы не наезжать на столбцы
  $("seatsLegend").textContent = `мест в самолётах: ${fmt(r.seats)}`;
}

function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

function showTip(x, yy, s, r) {
  const tip = $("tip");
  const level = Math.round(Number(s.quantile) * 100);
  tip.innerHTML = `<b>Сценарий ${s.quantile}</b><br>хотят: ${fmt(Math.max(s.want, 0))}<br>купят: ${fmt(s.buy)} из ${fmt(r.seats)}<br><span class="muted">спрос ниже этого в ${level}% случаев</span>`;
  tip.hidden = false;
  const box = $("chart").getBoundingClientRect();
  const scale = box.width / ($("chart").viewBox.baseVal.width || box.width);
  tip.style.left = `${Math.min(x * scale + 10, box.width - tip.offsetWidth - 4)}px`;
  tip.style.top = `${Math.max(yy * scale - 20, 0)}px`;
}
function hideTip() { $("tip").hidden = true; }

// ---------------- календарь ----------------
async function loadCalendar() {
  const r = currentRoute();
  $("calRoute").textContent = `${r.origin} → ${r.destination}`;
  try {
    const data = await api(`/api/calendar/${r.code}`);
    renderCalendar(data.days);
  } catch (err) {
    if (err.status === 401) showAuth();
  }
}

function renderCalendar(days) {
  const box = $("calendar");
  box.replaceChildren();
  ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].forEach((d) => {
    const h = document.createElement("div");
    h.className = "dow";
    h.textContent = d;
    box.appendChild(h);
  });
  const first = new Date(`${days[0].date}T00:00:00`);
  for (let i = 0; i < (first.getDay() + 6) % 7; i++) box.appendChild(document.createElement("div"));
  const css = getComputedStyle(document.documentElement);
  days.forEach((d) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "day";
    b.dataset.date = d.date;
    // цвет = давление спроса: вероятность распродать рейс по базовой цене (10% → светлый, 90% → насыщенный)
    const t = Math.min(1, Math.max(0, (d.sellout_at_base.value - 0.1) / 0.8));
    b.style.background = `color-mix(in srgb, ${css.getPropertyValue("--cal-1").trim()} ${Math.round(t * 100)}%, ${css.getPropertyValue("--cal-0").trim()})`;
    if (t > 0.45) b.classList.add("hot");
    const dt = new Date(`${d.date}T00:00:00`);
    b.innerHTML = `<span class="n">${dt.getDate()}.${String(dt.getMonth() + 1).padStart(2, "0")}</span><span class="p">${fmt(d.price)}</span><span class="s">распрод. ${d.sellout_at_base.label}</span>`;
    b.title = `${d.date}: спрос при базовой цене ${fmt(d.demand_base)}, мест ${fmt(d.seats)}, заполняемость при рекомендованной цене ${Math.round(d.load * 100)}%`;
    b.addEventListener("click", () => {
      $("date").value = d.date;
      markSelectedDay();
      calculate(false);
      $("fcForm").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    box.appendChild(b);
  });
  markSelectedDay();
}

function markSelectedDay() {
  document.querySelectorAll(".day").forEach((d) => d.classList.toggle("sel", d.dataset.date === $("date").value));
}

// ---------------- история ----------------
async function loadHistory() {
  try {
    const items = await api("/api/history");
    const list = $("history");
    list.replaceChildren();
    if (!items.length) {
      list.innerHTML = '<li class="muted">Пока пусто: нажми «Рассчитать и сохранить».</li>';
      return;
    }
    items.forEach((h) => {
      const li = document.createElement("li");
      li.textContent = h.summary;
      const t = document.createElement("time");
      t.textContent = new Date(h.created_at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
      li.appendChild(t);
      list.appendChild(li);
    });
  } catch (err) {
    if (err.status === 401) showAuth();
  }
}

// ---------------- выпадающие списки «Откуда» / «Куда» ----------------
const ICONS = {
  takeoff: "M2.5 19h19v2h-19v-2zm19.57-9.36c-.21-.8-1.04-1.28-1.84-1.06L14.92 10 8 3.57l-1.93.51 4.14 7.17-4.97 1.33-1.97-1.54-1.45.39 2.59 4.49L21 11.49c.81-.23 1.28-1.05 1.07-1.85z",
  landing: "M2.5 19h19v2h-19v-2zm7.18-5.73 4.35 1.16 5.31 1.42c.8.21 1.62-.26 1.84-1.06.21-.8-.26-1.62-1.06-1.84l-5.31-1.42-2.76-9.02L10.12 2v8.28L5.15 8.95l-.93-2.32-1.45-.39v5.17l1.6.43 5.31 1.43z",
  check: "M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
};
const svgIcon = (name, cls) =>
  `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name]}"/></svg>`;

function buildCombo(box, items) {
  const select = $(box.dataset.select);
  const labelId = `${box.dataset.select}Label`;
  box.innerHTML = `
    <button type="button" class="combo-btn" aria-haspopup="listbox" aria-expanded="false" aria-labelledby="${labelId}">
      ${svgIcon(box.dataset.icon, "combo-icon")}
      <span class="combo-value"><b></b><span class="combo-code"></span></span>
      <svg class="chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
    </button>
    <ul class="combo-panel" role="listbox" aria-labelledby="${labelId}" tabindex="-1" hidden></ul>`;
  const btn = box.querySelector(".combo-btn");
  const panel = box.querySelector(".combo-panel");
  let active = 0;

  items.forEach((it, i) => {
    const li = document.createElement("li");
    li.className = "combo-item";
    li.role = "option";
    li.dataset.value = it.value;
    li.innerHTML = `<span class="combo-code-tag">${it.code}</span>
      <span class="combo-text"><b>${it.title}</b><span>${it.meta}</span></span>${svgIcon("check", "combo-check")}`;
    li.addEventListener("click", () => choose(i));
    li.addEventListener("mousemove", () => highlight(i));
    panel.appendChild(li);
  });
  const options = [...panel.children];

  function render() {
    const it = items.find((x) => x.value === select.value) || items[0];
    btn.querySelector("b").textContent = it.title;
    btn.querySelector(".combo-code").textContent = it.code;
    options.forEach((o) => o.setAttribute("aria-selected", String(o.dataset.value === it.value)));
  }
  function highlight(i) {
    active = i;
    options.forEach((o, k) => o.classList.toggle("active", k === i));
    // прокручиваем только саму панель: scrollIntoView сдвигал бы всю страницу под курсором
    const o = options[i];
    if (o.offsetTop < panel.scrollTop) panel.scrollTop = o.offsetTop;
    else if (o.offsetTop + o.offsetHeight > panel.scrollTop + panel.clientHeight) {
      panel.scrollTop = o.offsetTop + o.offsetHeight - panel.clientHeight;
    }
  }
  function open() {
    document.querySelectorAll(".combo-btn[aria-expanded='true']").forEach((b) => b !== btn && b.click());
    panel.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    highlight(Math.max(0, items.findIndex((x) => x.value === select.value)));
    panel.focus({ preventScroll: true });
  }
  function close(focusBtn = true) {
    panel.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    if (focusBtn) btn.focus();
  }
  function choose(i) {
    const changed = select.value !== items[i].value;
    select.value = items[i].value;
    render();
    close();
    if (changed) select.dispatchEvent(new Event("change"));
  }

  btn.addEventListener("click", () => (panel.hidden ? open() : close()));
  btn.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(); }
  });
  panel.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); highlight(Math.min(items.length - 1, active + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); highlight(Math.max(0, active - 1)); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(active); }
    else if (e.key === "Escape" || e.key === "Tab") close(e.key === "Escape");
  });
  document.addEventListener("click", (e) => { if (!box.contains(e.target) && !panel.hidden) close(false); });
  render();
}

// ---------------- старт ----------------
(async function init() {
  info = await api("/api/routes");
  const dest = $("destination");
  info.routes.forEach((r) => {
    const o = document.createElement("option");
    o.value = r.destination;
    o.textContent = r.destination;
    dest.appendChild(o);
  });
  dest.value = info.routes.some((r) => r.destination === "Сочи") ? "Сочи" : info.routes[0].destination;
  buildCombo(document.querySelector('[data-select="origin"]'), [
    { value: "Москва", title: "Москва", code: "MOW", meta: "все рейсы в прогнозе — из Москвы" },
  ]);
  buildCombo(document.querySelector('[data-select="destination"]'), info.routes.map((r) => ({
    value: r.destination,
    title: r.destination,
    code: r.code.split("-")[1],
    meta: `базовая цена ${rub(r.base_price)}`,
  })));
  $("date").min = info.first_day;
  $("date").max = info.last_day;
  $("date").value = info.first_day <= "2026-06-12" && "2026-06-12" <= info.last_day ? "2026-06-12" : info.first_day;
  syncPriceBounds(true);
  window.addEventListener("resize", () => lastResult && drawChart(lastResult));
  const me = await api("/api/me");
  me.login ? showApp(me.login) : showAuth();
})();
