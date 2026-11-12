"use strict";
/* ✈️ Cheap flights viewer — reads data/flights.json + data/history.json produced by the GitHub Action. */

// ------------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
};

const MONTHS = ["იან", "თებ", "მარ", "აპრ", "მაი", "ივნ", "ივლ", "აგვ", "სექ", "ოქტ", "ნოე", "დეკ"];
const WD = ["კვი", "ორშ", "სამ", "ოთხ", "ხუთ", "პარ", "შაბ"]; // getUTCDay order
const WD_ORDER = [1, 2, 3, 4, 5, 6, 0];
const GEO = { TBS: "თბილისი", KUT: "ქუთაისი", BUS: "ბათუმი" };

const ms = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
const iso = (t) => new Date(t).toISOString().slice(0, 10);
const addDays = (s, n) => iso(ms(s) + n * 864e5);
const daysBetween = (a, b) => Math.round((ms(b) - ms(a)) / 864e5);
const wday = (s) => new Date(ms(s)).getUTCDay();
const fmtDate = (s) => `${+s.slice(8, 10)} ${MONTHS[+s.slice(5, 7) - 1]}`;
const fmtDateW = (s) => `${fmtDate(s)} (${WD[wday(s)]})`;
const fmtDur = (m) => (m ? `${Math.floor(m / 60)}სთ ${String(m % 60).padStart(2, "0")}წთ` : "—");
const fmtTr = (n) => (n === 0 ? "პირდაპირი" : `${n} გადაჯდომა`);
const gel = (p) => `${Math.round(p)}₾`;

// ------------------------------------------------------------------ state
const S = { data: null, H: { legs: {}, roundtrips: {}, routes: {} }, legs: [], rts: [], trips: [], shown: 0, f: null };
const PAGE = 60;
const PRICE_CHIPS = [100, 150, 250, 300];
const icon = (id, cls = "i") => `<svg class="${cls}"><use href="#i-${id}"/></svg>`;

function place(code) { return (S.data && S.data.places[code]) || { city: code, name: code, country: "" }; }
function cityOf(code) { return place(code).city || code; }
function nameOf(code) {
  const cities = (S.data && S.data.cities) || {};
  return GEO[code] || GEO[cityOf(code)] || (S.data && S.data.places[code] && S.data.places[code].name) || cities[cityOf(code)] || cities[code] || code;
}
function isDomestic(code) { return place(code).country === "GE" || GEO[code] || GEO[cityOf(code)]; }
function airline(code) { return (S.data && S.data.airlines[code]) || code || "?"; }

function defaults() {
  const s = (S.data && S.data.settings) || {};
  return {
    pmin: "", pmax: s.max_price_gel ?? 220, nmin: s.min_nights ?? 3, nmax: s.max_nights ?? 7,
    dfrom: "", dto: "", rfrom: "", rto: "", wd: [], orig: ["TBS", "KUT"], ret: ["TBS", "KUT"],
    same: false, tr: s.max_transfers ?? 1, maxdur: "", alOff: [], q: "", dest: "", perCity: true, sort: "price",
  };
}

// ------------------------------------------------------------------ links
const ddmm = (s) => s.slice(8, 10) + s.slice(5, 7);
const yymmdd = (s) => s.slice(2, 4) + s.slice(5, 7) + s.slice(8, 10);
function wizzLink(o, x, d, r) { return `https://wizzair.com/en-gb/booking/select-flight/${o}/${x}/${d}/${r || "null"}/1/0/0/null`; }
function aviaLink(o, x, d, r) { return `https://www.aviasales.com/search/${o}${ddmm(d)}${x}${r ? ddmm(r) : ""}1`; }
function skyLink(o, x, d, r) { return `https://www.skyscanner.net/transport/flights/${o.toLowerCase()}/${x.toLowerCase()}/${yymmdd(d)}/${r ? yymmdd(r) + "/" : ""}?adultsv2=1`; }
function googleLink(o, x, d, r) {
  const q = r ? `Flights from ${o} to ${x} on ${d} returning ${r}` : `One way flights from ${o} to ${x} on ${d}`;
  return `https://www.google.com/travel/flights?q=${encodeURIComponent(q)}`;
}
function legLink(l) { return l.src === "wizzair" ? wizzLink(l.o, l.x, l.d) : aviaLink(l.o, l.x, l.d); }

// ------------------------------------------------------------------ data
function rows(fields, list) {
  return list.map((r) => { const o = {}; fields.forEach((f, i) => { o[f] = r[i]; }); return o; });
}

async function load() {
  try {
    const [d, h] = await Promise.all([
      fetch(`data/flights.json?t=${Date.now()}`, { cache: "no-store" }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }),
      fetch(`data/history.json?t=${Date.now()}`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
    ]);
    S.data = d;
    S.H = { legs: {}, roundtrips: {}, routes: {}, ...h };
    S.legs = rows(d.leg_fields, d.legs);
    S.rts = rows(d.rt_fields, d.roundtrips);
  } catch (e) {
    $("#updated").textContent = "მონაცემები ვერ ჩაიტვირთა";
    $("#results").innerHTML = `<div class="empty">მონაცემები ჯერ არ არის.<br>პირველი შემოწმების შემდეგ (GitHub Actions) აქ გამოჩნდება ფრენები.</div>`;
    return false;
  }
  S.loadedAt = Date.now();
  paintUpdated();
  return true;
}

function paintUpdated() {
  if (!S.data) return;
  const g = S.data.generated;
  const mins = Math.max(0, Math.round((Date.now() - Date.parse(g)) / 60000));
  const ago = mins < 60 ? `${mins} წთ წინ` : mins < 48 * 60 ? `${Math.round(mins / 60)} სთ წინ` : `${Math.round(mins / 1440)} დღის წინ`;
  $("#updated").textContent = `განახლდა ${ago} · ${fmtDate(g)} ${g.slice(11, 16)}`;
}

// pull fresh data: on open/return to the app, every 10 min while open, or on tap
async function refresh(force = false) {
  if (!S.f || (!force && Date.now() - (S.loadedAt || 0) < 2 * 60000)) { paintUpdated(); return; }
  const btn = $("#refreshBtn");
  btn && btn.classList.add("spin");
  const before = S.data && S.data.generated;
  if (await load()) {
    if (S.data.generated !== before) {
      buildForm(); syncForm(); renderTrips();
      if ($("#tab-history").classList.contains("active")) renderHistory();
      if ($("#tab-settings").classList.contains("active")) renderSettings();
    }
  }
  btn && btn.classList.remove("spin");
}

// ------------------------------------------------------------------ trips
function inRange(d, a, b) { return (!a || d >= a) && (!b || d <= b); }

function computeTrips(f, opts = {}) {
  const pmin = f.pmin === "" ? 0 : +f.pmin;
  const pmax = f.pmax === "" || f.pmax == null ? Infinity : +f.pmax;
  const maxdur = f.maxdur ? +f.maxdur : 0;
  const alOff = new Set(f.alOff);
  const wd = new Set(f.wd);
  const q = (opts.city ? "" : (f.q || "").trim().toLowerCase());
  const legOk = (l) => l.tr <= f.tr && !alOff.has(l.al) && (!maxdur || !l.dur || l.dur <= maxdur);
  const destOk = (x) => {
    if (opts.city) return cityOf(x) === opts.city;
    if (f.dest && cityOf(x) !== f.dest) return false;
    if (!q) return true;
    const p = place(x);
    return [x, p.city, p.name, p.country].some((v) => String(v || "").toLowerCase().includes(q));
  };

  // cheapest return leg per (city, date, Georgian airport)
  const back = new Map();
  for (const l of S.legs) {
    if (!f.ret.includes(l.x) || isDomestic(l.o) || !legOk(l) || !inRange(l.d, f.rfrom, f.rto)) continue;
    const k = `${cityOf(l.o)}|${l.d}|${l.x}`;
    const cur = back.get(k);
    if (!cur || l.p < cur.p) back.set(k, l);
  }

  const best = new Map(); // dedupe identical itineraries
  const add = (t) => {
    if (t.price < pmin || t.price > pmax) return;
    const k = `${t.o}|${t.x}|${t.d}|${t.rf}|${t.rt}|${t.r}`;
    const cur = best.get(k);
    if (!cur || t.price < cur.price) best.set(k, t);
  };

  for (const l of S.legs) {
    if (!f.orig.includes(l.o) || isDomestic(l.x) || !legOk(l) || !inRange(l.d, f.dfrom, f.dto)) continue;
    if (wd.size && !wd.has(wday(l.d))) continue;
    if (!destOk(l.x)) continue;
    const city = cityOf(l.x);
    for (let n = +f.nmin; n <= +f.nmax; n++) {
      const r = addDays(l.d, n);
      for (const ra of f.ret) {
        if (f.same && ra !== l.o) continue;
        const b = back.get(`${city}|${r}|${ra}`);
        if (b) add({ kind: "pair", o: l.o, x: l.x, rf: b.o, rt: b.x, d: l.d, r, n, price: l.p + b.p, out: l, back: b, city });
      }
    }
  }

  for (const t of S.rts) {
    const n = daysBetween(t.d, t.r);
    if (!f.orig.includes(t.o) || !f.ret.includes(t.o) || isDomestic(t.x)) continue;
    if (n < +f.nmin || n > +f.nmax || t.tr > f.tr || alOff.has(t.al)) continue;
    if (maxdur && ((t.dto && t.dto > maxdur) || (t.dback && t.dback > maxdur))) continue;
    if (!inRange(t.d, f.dfrom, f.dto) || !inRange(t.r, f.rfrom, f.rto)) continue;
    if (wd.size && !wd.has(wday(t.d))) continue;
    if (!destOk(t.x)) continue;
    add({ kind: "rt", o: t.o, x: t.x, rf: t.x, rt: t.o, d: t.d, r: t.r, n, price: t.p, fare: t, city: cityOf(t.x) });
  }

  let list = [...best.values()];
  if (f.perCity && !opts.city) {
    const per = new Map();
    for (const t of list) { const c = per.get(t.city); if (!c || t.price < c.price) per.set(t.city, t); }
    list = [...per.values()];
  }
  const dur = (t) => (t.kind === "rt" ? (t.fare.dto || 0) + (t.fare.dback || 0) : (t.out.dur || 0) + (t.back.dur || 0)) || 1e9;
  const sorters = {
    price: (a, b) => a.price - b.price || a.d.localeCompare(b.d),
    date: (a, b) => a.d.localeCompare(b.d) || a.price - b.price,
    duration: (a, b) => dur(a) - dur(b) || a.price - b.price,
    nights: (a, b) => b.n - a.n || a.price - b.price,
  };
  return list.sort(sorters[f.sort] || sorters.price);
}

// ------------------------------------------------------------------ history
function stepUnion(a, b) {
  // two change-only series → their sum on every day either changed (carry forward)
  const days = [...new Set([...a.map((p) => p[0]), ...b.map((p) => p[0])])].sort();
  const out = []; let i = 0, j = 0, va = null, vb = null;
  for (const d of days) {
    while (i < a.length && a[i][0] <= d) va = a[i++][1];
    while (j < b.length && b[j][0] <= d) vb = b[j++][1];
    if (va != null && vb != null) {
      const v = va + vb;
      if (!out.length || out[out.length - 1][1] !== v) out.push([d, v]);
    }
  }
  return out;
}

function tripHistory(t) {
  if (t.kind === "rt") return S.H.roundtrips[`${t.o}|${t.x}|${t.d}|${t.r}`] || null;
  const a = S.H.legs[`${t.o}|${t.x}|${t.d}`], b = S.H.legs[`${t.rf}|${t.rt}|${t.r}`];
  return a && b ? stepUnion(a, b) : null;
}

function trendHtml(t) {
  const h = tripHistory(t);
  if (!h || h.length < 2) return "";
  const diff = Math.round(h[h.length - 1][1] - h[0][1]);
  if (diff < 0) return `<span class="pill green">−${-diff}₾ ${fmtDate(h[0][0])}-დან</span>`;
  if (diff > 0) return `<span class="pill up">+${diff}₾</span>`;
  return "";
}

// ------------------------------------------------------------------ chart (single series, step line + hover)
function niceTicks(lo, hi, n = 4) {
  const span = hi - lo || 1;
  const step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const ticks = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(Math.round(v));
  return ticks;
}

function renderChart(el, series, { ref, endDay } = {}) {
  if (!series || !series.length) { el.innerHTML = `<p class="muted small">ისტორია ჯერ არ არის.</p>`; return; }
  const pts = series.slice();
  const lastDay = endDay && endDay > pts[pts.length - 1][0] ? endDay : pts[pts.length - 1][0];
  const W = 600, H = 210, L = 44, R = 12, T = 12, B = 26;
  const x0 = ms(pts[0][0]), x1 = Math.max(ms(lastDay), x0 + 864e5);
  let lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
  const showRef = ref && ref <= hi * 1.3 && ref >= lo * 0.7;
  if (showRef) { lo = Math.min(lo, ref); hi = Math.max(hi, ref); }
  const pad = Math.max(10, (hi - lo) * 0.15); lo = Math.max(0, lo - pad); hi += pad;
  const X = (d) => L + ((ms(d) - x0) / (x1 - x0)) * (W - L - R);
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

  let path = `M${X(pts[0][0])},${Y(pts[0][1])}`;
  for (let i = 1; i < pts.length; i++) path += `H${X(pts[i][0])}V${Y(pts[i][1])}`;
  path += `H${X(lastDay)}`;
  const area = `${path}V${Y(lo)}H${X(pts[0][0])}Z`;
  const yt = niceTicks(lo, hi);
  const xt = [pts[0][0], lastDay].concat(pts.length > 2 ? [pts[Math.floor(pts.length / 2)][0]] : []);
  const uniqXt = [...new Set(xt)].sort();

  el.innerHTML = `
    <div class="chart">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="ფასის ისტორია">
        <g class="grid">${yt.map((v) => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/>`).join("")}</g>
        <g class="axis">
          ${yt.map((v) => `<text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${v}₾</text>`).join("")}
          ${uniqXt.map((d, i) => `<text x="${X(d)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === uniqXt.length - 1 ? "end" : "middle"}">${fmtDate(d)}</text>`).join("")}
        </g>
        ${showRef ? `<line class="ref" x1="${L}" x2="${W - R}" y1="${Y(ref)}" y2="${Y(ref)}"/><text class="ref-label" x="${W - R}" y="${Y(ref) - 5}" text-anchor="end">ზღვარი ${ref}₾</text>` : ""}
        <path class="area" d="${area}"/>
        <path class="series" d="${path}"/>
        ${pts.map((p) => `<circle class="dot" cx="${X(p[0])}" cy="${Y(p[1])}" r="4"/>`).join("")}
        <line class="cross" y1="${T}" y2="${H - B}" visibility="hidden"/>
        <circle class="dot hover" r="5" visibility="hidden"/>
        <rect x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent" class="hit"/>
      </svg>
      <div class="tip" hidden></div>
    </div>
    <details><summary>ცხრილის სახით</summary>
      <table class="chart-table"><thead><tr><th>თარიღი</th><th>ფასი</th></tr></thead>
      <tbody>${pts.slice().reverse().map((p) => `<tr><td>${fmtDateW(p[0])}</td><td>${gel(p[1])}</td></tr>`).join("")}</tbody></table>
    </details>`;

  const svg = $("svg", el), tip = $(".tip", el), cross = $(".cross", el), hov = $(".hover", el);
  const days = []; // every day from first to last, with carried-forward price
  for (let d = pts[0][0], i = 0, v = pts[0][1]; d <= lastDay; d = addDays(d, 1)) {
    while (i < pts.length && pts[i][0] <= d) v = pts[i++][1];
    days.push([d, v]);
  }
  const move = (ev) => {
    const r = svg.getBoundingClientRect();
    const sx = ((ev.clientX - r.left) / r.width) * W;
    const t = x0 + ((sx - L) / (W - L - R)) * (x1 - x0);
    let best = days[0];
    for (const p of days) if (Math.abs(ms(p[0]) - t) < Math.abs(ms(best[0]) - t)) best = p;
    const cx = X(best[0]), cy = Y(best[1]);
    cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
    hov.setAttribute("cx", cx); hov.setAttribute("cy", cy); hov.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.innerHTML = `${fmtDateW(best[0])} · <b>${gel(best[1])}</b>`;
    tip.style.left = `${Math.min(Math.max((cx / W) * r.width, 60), r.width - 60)}px`;
    tip.style.top = `${(cy / H) * r.height}px`;
  };
  const leave = () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); hov.setAttribute("visibility", "hidden"); };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerdown", move);
  svg.addEventListener("pointerleave", leave);
}

function sparkline(series) {
  if (!series || series.length < 2) return "";
  const W = 110, H = 32, vals = series.map((p) => p[1]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const x0 = ms(series[0][0]), x1 = ms(series[series.length - 1][0]) || x0 + 1;
  const X = (d) => 2 + ((ms(d) - x0) / (x1 - x0 || 1)) * (W - 4);
  const Y = (v) => 3 + (1 - (v - lo) / (hi - lo || 1)) * (H - 6);
  let d = `M${X(series[0][0])},${Y(series[0][1])}`;
  for (let i = 1; i < series.length; i++) d += `H${X(series[i][0])}V${Y(series[i][1])}`;
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"><path d="${d}"/></svg>`;
}

// ------------------------------------------------------------------ trips UI
function routeText(t) {
  return t.o === t.rt && t.x === t.rf ? `${t.o} ⇄ ${t.x}` : `${t.o} → ${t.x} · ${t.rf} → ${t.rt}`;
}

function cardHtml(t, i) {
  const als = t.kind === "rt" ? [t.fare.al] : [...new Set([t.out.al, t.back.al])];
  const tr = t.kind === "rt" ? t.fare.tr : Math.max(t.out.tr, t.back.tr);
  const route = t.o === t.rt && t.x === t.rf
    ? `${t.o} ${icon("swap")} ${t.x}`
    : `${t.o} ${icon("arrow")} ${t.x}${t.x !== t.rf ? ` · ${t.rf}` : ""} ${icon("arrow")} ${t.rt}`;
  return `<button class="card" type="button" data-i="${i}">
      <div class="dest">${esc(nameOf(t.x))}<small>${esc(place(t.x).country)}</small></div>
      <div class="price">${gel(t.price)}</div>
      <div class="dates">${fmtDateW(t.d)} – ${fmtDateW(t.r)}</div>
      <div class="nights">${t.n} ღამე</div>
      <div class="meta">
        <span class="route">${route}</span>
        <span>${esc(als.map(airline).join(" + "))}</span>
        <span class="pill ${tr === 0 ? "green" : ""}">${fmtTr(tr)}</span>
        ${t.kind === "rt" ? `<span class="pill">ერთიანი ბილეთი</span>` : ""}
        ${trendHtml(t)}
      </div>
    </button>`;
}

function renderTrips(reset = true) {
  if (!S.data) return;
  if (reset) { S.trips = computeTrips(S.f); S.shown = 0; $("#results").innerHTML = ""; }
  const next = S.trips.slice(S.shown, S.shown + PAGE);
  $("#results").insertAdjacentHTML("beforeend", next.map((t, k) => cardHtml(t, S.shown + k)).join(""));
  S.shown += next.length;
  $("#more").hidden = S.shown >= S.trips.length;
  const n = S.trips.length;
  $("#resultCount").textContent = n ? `${n} ${S.f.perCity ? "მიმართულება" : "ვარიანტი"}` : "";
  if (!n) $("#results").innerHTML = `<div class="empty">${icon("plane")}<br>ამ ფილტრებით ფრენა ვერ მოიძებნა.<br>სცადე მეტი თანხა ან სხვა თარიღები.</div>`;
  $("#sheetCount").textContent = `(${n})`;
  const active = activeFilterCount();
  $("#filterCount").hidden = !active; $("#filterCount").textContent = active;
  renderPriceRow();
  renderDestSelect();
}

function activeFilterCount() {
  const d = defaults(), f = S.f;
  let c = 0;
  for (const k of ["pmin", "nmin", "nmax", "dfrom", "dto", "rfrom", "rto", "same", "tr", "maxdur", "q", "perCity"]) if (String(f[k]) !== String(d[k])) c++;
  if (f.wd.length) c++; if (f.alOff.length) c++;
  if (f.orig.length !== 2) c++; if (f.ret.length !== 2) c++;
  return c;
}

function renderPriceRow() {
  const f = S.f, cur = f.pmax === "" || f.pmax == null ? "" : String(+f.pmax);
  const custom = cur !== "" && !PRICE_CHIPS.includes(+cur);
  const row = $("#priceRow");
  const focused = document.activeElement && document.activeElement.id === "customPrice";
  if (focused) return; // don't steal the keyboard while typing
  row.innerHTML = PRICE_CHIPS.map((v) => `<button class="chip" type="button" data-qp="${v}" aria-pressed="${cur === String(v)}">${v}₾</button>`).join("") +
    `<label class="chip-input ${custom ? "on" : ""}"><span class="sr-only">სხვა თანხა</span>
       <input id="customPrice" type="number" inputmode="numeric" placeholder="სხვა თანხა" value="${custom ? cur : ""}"><span class="cur">₾</span></label>` +
    `<button class="chip" type="button" data-qp="" aria-pressed="${cur === ""}">ნებისმიერი</button>`;
}

function renderDestSelect() {
  const sel = $("#destSelect");
  const per = computeTrips({ ...S.f, dest: "", perCity: true, sort: "price" });
  const seen = new Set(per.map((t) => t.city));
  const opts = per.map((t) => `<option value="${esc(t.city)}">${esc(nameOf(t.x))} · ${gel(t.price)}</option>`);
  if (S.f.dest && !seen.has(S.f.dest)) opts.unshift(`<option value="${esc(S.f.dest)}">${esc(nameOf(S.f.dest))}</option>`);
  sel.innerHTML = `<option value="">ყველა მიმართულება (${per.length})</option>` + opts.join("");
  sel.value = S.f.dest || "";
}

// ------------------------------------------------------------------ detail
function legHtml(label, l) {
  const arrDate = l.arr ? l.arr.slice(0, 10) : "";
  const plus = arrDate && arrDate !== l.d ? `<sup>+${daysBetween(l.d, arrDate)}</sup>` : "";
  return `<div class="leg">
    <div class="leg-head"><span><b>${label}</b> · ${fmtDateW(l.d)}</span><span>${l.p != null ? gel(l.p) : ""}</span></div>
    <div class="leg-times">
      <div><div class="t">${esc(l.t || "—")}</div><div class="code">${esc(l.o)} · ${esc(nameOf(l.o))}</div></div>
      <div class="mid">${l.est ? "≈ " : ""}${fmtDur(l.dur)}<div class="bar">${icon("plane")}</div>${fmtTr(l.tr)}</div>
      <div style="text-align:right"><div class="t">${l.arr ? esc(l.arr.slice(11, 16)) + plus : "—"}</div><div class="code">${esc(l.x)} · ${esc(nameOf(l.x))}</div></div>
    </div>
    <dl>
      <dt>ავიაკომპანია</dt><dd>${esc(airline(l.al))}${l.fn ? ` · ${esc(l.al)} ${esc(l.fn)}` : ""}</dd>
      <dt>ფრენის დრო</dt><dd>${l.dur ? fmtDur(l.dur) + (l.est ? " · სავარაუდო" : "") + (l.tr ? " · გადაჯდომის ჩათვლით" : "") : "უცნობია"}</dd>
      ${arrDate ? `<dt>ჩაფრენა</dt><dd>${fmtDateW(arrDate)}, ${esc(l.arr.slice(11, 16))} ადგილობრივი დროით</dd>` : ""}
      ${l.src ? `<dt>წყარო</dt><dd>${l.src === "wizzair" ? "wizzair.com" : "Aviasales"}</dd>` : ""}
    </dl>
  </div>`;
}

function openDetail(t) {
  const legs = t.kind === "rt"
    ? [{ o: t.o, x: t.x, d: t.d, t: t.fare.t, dur: t.fare.dto, tr: t.fare.tr, al: t.fare.al, fn: t.fare.fn, src: "travelpayouts" },
       { o: t.x, x: t.o, d: t.r, t: t.fare.rt, dur: t.fare.dback, tr: t.fare.tr, al: t.fare.al, fn: "", src: "travelpayouts" }]
    : [t.out, t.back];
  const sameAirports = t.o === t.rt && t.x === t.rf;
  const actions = t.kind === "rt"
    ? [["დაჯავშნა", aviaLink(t.o, t.x, t.d, t.r), true]]
    : (t.out.src === "wizzair" && t.back.src === "wizzair" && sameAirports)
      ? [["დაჯავშნა Wizz Air-ზე", wizzLink(t.o, t.x, t.d, t.r), true]]
      : [["წასვლის ბილეთი", legLink(t.out), true], ["დაბრუნების ბილეთი", legLink(t.back), true]];
  if (sameAirports) actions.push(["Skyscanner", skyLink(t.o, t.x, t.d, t.r)], ["Google Flights", googleLink(t.o, t.x, t.d, t.r)]);
  else actions.push(["Google · წასვლა", googleLink(t.o, t.x, t.d)], ["Google · დაბრუნება", googleLink(t.rf, t.rt, t.r)]);
  const nPrimary = actions.filter((a) => a[2]).length;

  const others = computeTrips({ ...S.f, perCity: false, sort: "price" }, { city: t.city })
    .filter((o) => !(o.d === t.d && o.r === t.r && o.o === t.o && o.rt === t.rt)).slice(0, 6);
  S.others = others;
  const h = tripHistory(t);
  const vals = h ? h.map((p) => p[1]) : [];

  $("#detailTitle").textContent = nameOf(t.x);
  $("#detailBody").innerHTML = `
    <div class="trip-head">
      <div><div class="when">${fmtDateW(t.d)} – ${fmtDateW(t.r)}</div><div class="muted small">${t.n} ღამე · ${esc(routeText(t))}</div></div>
      <div class="price">${gel(t.price)}</div>
    </div>
    <div class="legs">${legHtml("წასვლა", legs[0])}${legHtml("დაბრუნება", legs[1])}</div>
    ${t.kind === "rt" ? `<p class="note">ერთიანი ორმხრივი ბილეთი — ფასი ორივე მიმართულებისაა.</p>` : ""}
    <div class="actions">${actions.map(([l, u, primary]) => `<a class="btn ${primary ? "primary" : ""}" ${primary && nPrimary === 2 ? 'style="grid-column:auto"' : ""} href="${esc(u)}" target="_blank" rel="noopener">${l}</a>`).join("")}</div>
    <p class="note">ფასი ერთ მგზავრზეა, ბარგის გარეშე. დაჯავშნამდე გადაამოწმე საიტზე.</p>
    <div class="panel">
      <h3>ფასის ისტორია ამ თარიღებზე</h3>
      ${vals.length ? `<div class="stats"><span>მინიმუმი<b>${gel(Math.min(...vals))}</b></span><span>მაქსიმუმი<b>${gel(Math.max(...vals))}</b></span><span>ვაკვირდებით<b>${fmtDate(h[0][0])}-დან</b></span></div>` : ""}
      <div id="tripChart"></div>
    </div>
    <div class="panel">
      <h3>${esc(nameOf(t.x))} · ყველაზე იაფი მოგზაურობა დღეების მიხედვით</h3>
      <div id="cityChart"></div>
    </div>
    ${others.length ? `<h3 style="margin:20px 2px 0">სხვა თარიღები</h3><div class="cards" id="othersList">${others.map((o, i) => cardHtml(o, i)).join("")}</div>` : ""}
  `;
  const ref = S.data.settings && S.data.settings.max_price_gel;
  renderChart($("#tripChart"), h, { ref, endDay: S.H.updated });
  renderChart($("#cityChart"), S.H.routes[t.city], { ref, endDay: S.H.updated });
  const dlg = $("#detailSheet");
  if (!dlg.open) dlg.showModal();
  $(".sheet-body", dlg).scrollTop = 0;
}

function openCityHistory(city) {
  const s = S.H.routes[city];
  const vals = s.map((p) => p[1]);
  $("#detailTitle").textContent = nameOf(city);
  $("#detailBody").innerHTML = `
    <div class="stats"><span>ახლა<b>${gel(vals[vals.length - 1])}</b></span><span>მინიმუმი<b>${gel(Math.min(...vals))}</b></span><span>მაქსიმუმი<b>${gel(Math.max(...vals))}</b></span></div>
    <div id="cityChart"></div>
    <button class="btn primary wide" id="showCityTrips" type="button">ფრენების ნახვა</button>`;
  renderChart($("#cityChart"), s, { ref: S.data.settings && S.data.settings.max_price_gel, endDay: S.H.updated });
  $("#showCityTrips").onclick = () => {
    S.f.dest = city; S.f.q = "";
    S.f.perCity = false; saveFilters(); syncForm(); renderTrips(); $("#detailSheet").close(); switchTab("trips");
  };
  $("#detailSheet").showModal();
}

// ------------------------------------------------------------------ history tab
function renderHistory() {
  const q = ($("#histSearch").value || "").toLowerCase();
  const items = Object.entries(S.H.routes || {})
    .filter(([c]) => !q || [c, nameOf(c)].some((v) => v.toLowerCase().includes(q)))
    .map(([c, s]) => ({ c, s, now: s[s.length - 1][1], min: Math.min(...s.map((p) => p[1])) }))
    .sort((a, b) => a.now - b.now);
  $("#historyList").innerHTML = items.length ? items.map((it) => `
    <button class="card hist-card" type="button" data-city="${esc(it.c)}">
      <div class="dest">${esc(nameOf(it.c))}</div>
      ${sparkline(it.s)}
      <div class="dates"><span class="price" style="font-size:16px">${gel(it.now)}</span> <span class="muted small">· მინ. ${gel(it.min)} · ${fmtDate(it.s[0][0])}-დან</span></div>
    </button>`).join("") : `<div class="empty">${icon("chart")}<br>ისტორია რამდენიმე შემოწმების შემდეგ გამოჩნდება.</div>`;
}

// ------------------------------------------------------------------ settings tab
function renderSettings() {
  const s = (S.data && S.data.settings) || {};
  $("#currentSettings").innerHTML = S.data ? `
    <div class="stats" style="margin:0">
      <span>სტატუსი<b>${s.paused ? "პაუზაზე" : "აქტიური"}</b></span><span>ზღვარი<b>${s.max_price_gel}₾</b></span>
      <span>ღამეები<b>${s.min_nights}–${s.max_nights}</b></span><span>გადაჯდომა<b>${s.max_transfers === 0 ? "არა" : `მაქს. ${s.max_transfers}`}</b></span>
    </div>` : "";
  $("#setPrice").value = s.max_price_gel ?? "";
  $("#setNMin").value = s.min_nights ?? "";
  $("#setNMax").value = s.max_nights ?? "";
  $("#setTr").value = String(s.max_transfers ?? 1);
  $("#topic").value = store.get("topic", "");
  if (S.data) {
    const errs = Object.entries(S.data.errors || {});
    $("#dataInfo").innerHTML = `ბოლო განახლება: ${esc(S.data.generated.replace("T", " "))}<br>
      ერთი მიმართულების ფასები: ${S.legs.length} · ორმხრივი ბილეთები: ${S.rts.length}<br>
      ${errs.length ? `პრობლემა: ${errs.map(([k, v]) => `${esc(k)} — ${esc(v)}`).join("<br>")}` : "ყველა წყარო მუშაობს"}`;
  }
}

async function sendCommand(cmd) {
  const topic = ($("#topic").value || "").trim();
  const out = $("#sendResult");
  if (!topic) { out.textContent = "ჯერ ჩაწერე ntfy თემა."; return; }
  store.set("topic", topic);
  const body = {
    price: () => $("#setPrice").value,
    nights: () => `ღამე ${$("#setNMin").value}-${$("#setNMax").value}`,
    transfers: () => ($("#setTr").value === "0" ? "პირდაპირი" : `გადაჯდომა ${$("#setTr").value}`),
    pause: () => "პაუზა", resume: () => "ჩართვა", status: () => "სტატუსი",
  }[cmd]();
  out.textContent = "იგზავნება…";
  try {
    const r = await fetch(`https://ntfy.sh/${encodeURIComponent(topic)}-settings`, { method: "POST", body });
    if (!r.ok) throw new Error(r.status);
    out.textContent = `გაიგზავნა: «${body}». ამოქმედდება შემდეგ შემოწმებაზე.`;
  } catch (e) {
    out.textContent = `ვერ გაიგზავნა (${e.message}).`;
  }
}

// ------------------------------------------------------------------ filter form
function saveFilters() { store.set("filters", S.f); }

function syncForm() {
  const form = $("#filterForm"), f = S.f;
  for (const k of ["pmin", "pmax", "nmin", "nmax", "dfrom", "dto", "rfrom", "rto", "maxdur", "q"]) form.elements[k].value = f[k] ?? "";
  form.elements.same.checked = !!f.same;
  form.elements.perCity.checked = !!f.perCity;
  $$("[data-preset=pmax] button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === String(f.pmax ?? ""))));
  $$("[data-single=tr] button").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.v === +f.tr)));
  $$("[data-multi=wd] button").forEach((b) => b.setAttribute("aria-pressed", String(f.wd.includes(+b.dataset.v))));
  $$("[data-multi=orig] button").forEach((b) => b.setAttribute("aria-pressed", String(f.orig.includes(b.dataset.v))));
  $$("[data-multi=ret] button").forEach((b) => b.setAttribute("aria-pressed", String(f.ret.includes(b.dataset.v))));
  $$("[data-multi=al] button").forEach((b) => b.setAttribute("aria-pressed", String(!f.alOff.includes(b.dataset.v))));
  $("#sort").value = f.sort;
}

function buildForm() {
  const form = $("#filterForm");
  const opts = Array.from({ length: 14 }, (_, i) => `<option value="${i + 1}">${i + 1}</option>`).join("");
  form.elements.nmin.innerHTML = opts; form.elements.nmax.innerHTML = opts;
  $("#weekdays").innerHTML = WD_ORDER.map((d) => `<button type="button" data-v="${d}">${WD[d]}</button>`).join("");
  const origins = (S.data && S.data.origins) || ["TBS", "KUT"];
  for (const k of ["orig", "ret"]) $(`[data-multi=${k}]`).innerHTML = origins.map((o) => `<button type="button" data-v="${o}">${esc(nameOf(o))}</button>`).join("");
  // airlines sorted by how many prices they have
  const count = {};
  for (const l of S.legs) count[l.al] = (count[l.al] || 0) + 1;
  for (const r of S.rts) count[r.al] = (count[r.al] || 0) + 1;
  const als = Object.keys(count).filter(Boolean).sort((a, b) => count[b] - count[a]);
  $("#destList").innerHTML = Object.entries(S.data.cities || {}).map(([c, n]) => `<option value="${esc(n)}">${esc(c)}</option>`).join("");
  $("[data-multi=al]").innerHTML = als.map((a) => `<button type="button" data-v="${esc(a)}">${esc(airline(a))}</button>`).join("");
  const today = iso(Date.now());
  for (const k of ["dfrom", "dto", "rfrom", "rto"]) form.elements[k].min = today;
}

function wireForm() {
  const form = $("#filterForm");
  let timer;
  const changed = () => { clearTimeout(timer); timer = setTimeout(() => { saveFilters(); syncForm(); renderTrips(); }, 150); };
  form.addEventListener("input", (e) => {
    const el = e.target; if (!el.name) return;
    if (el.type === "checkbox") S.f[el.name] = el.checked;
    else if (["nmin", "nmax"].includes(el.name)) {
      S.f[el.name] = +el.value;
      if (S.f.nmin > S.f.nmax) { if (el.name === "nmin") S.f.nmax = S.f.nmin; else S.f.nmin = S.f.nmax; }
    } else S.f[el.name] = el.value;
    changed();
  });
  form.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]"); if (!b) return;
    const box = b.parentElement, v = b.dataset.v;
    if (box.dataset.preset === "pmax") S.f.pmax = v;
    else if (box.dataset.single === "tr") S.f.tr = +v;
    else if (box.dataset.multi === "wd") { const n = +v; S.f.wd = S.f.wd.includes(n) ? S.f.wd.filter((x) => x !== n) : [...S.f.wd, n]; }
    else if (box.dataset.multi === "orig" || box.dataset.multi === "ret") {
      const k = box.dataset.multi; const cur = S.f[k];
      S.f[k] = cur.includes(v) ? (cur.length > 1 ? cur.filter((x) => x !== v) : cur) : [...cur, v];
    } else if (box.dataset.multi === "al") S.f.alOff = S.f.alOff.includes(v) ? S.f.alOff.filter((x) => x !== v) : [...S.f.alOff, v];
    else return;
    changed();
  });
  $("#alAll").onclick = () => { S.f.alOff = []; changed(); };
  $("#alNone").onclick = () => { S.f.alOff = $$("[data-multi=al] button").map((b) => b.dataset.v); changed(); };
  $("#resetFilters").onclick = () => { S.f = defaults(); changed(); };
}

// ------------------------------------------------------------------ theme & tabs
function effectiveTheme() {
  const t = document.documentElement.dataset.theme;
  if (t) return t;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function paintThemeBtn() {
  const dark = effectiveTheme() === "dark";
  $("#themeBtn").innerHTML = icon(dark ? "sun" : "moon");
  $("#themeBtn").setAttribute("aria-label", dark ? "ღია რეჟიმი" : "მუქი რეჟიმი");
}
function switchTab(name) {
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
  $$(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  if (name === "history") renderHistory();
  if (name === "settings") renderSettings();
  scrollTo(0, 0);
}

function openFromHash() {
  const m = location.hash.match(/trip=([A-Z]{3})\.([A-Z]{3})\.(\d{4}-\d\d-\d\d)\.([A-Z]{3})\.([A-Z]{3})\.(\d{4}-\d\d-\d\d)/);
  if (!m || !S.data) return;
  const [, o, x, d, rf, rt, r] = m;
  const cheapest = (pred) => S.legs.filter(pred).sort((a, b) => a.p - b.p)[0];
  const out = cheapest((l) => l.o === o && l.x === x && l.d === d);
  const back = cheapest((l) => l.o === rf && l.x === rt && l.d === r);
  const fare = S.rts.filter((t) => t.o === o && t.x === x && t.d === d && t.r === r).sort((a, b) => a.p - b.p)[0];
  let t = null;
  if (out && back) t = { kind: "pair", o, x, rf, rt, d, r, n: daysBetween(d, r), price: out.p + back.p, out, back, city: cityOf(x) };
  if (fare && (!t || fare.p < t.price)) t = { kind: "rt", o, x, rf: x, rt: o, d, r, n: daysBetween(d, r), price: fare.p, fare, city: cityOf(x) };
  if (t) openDetail(t);
  history.replaceState(null, "", location.pathname);
}

// ------------------------------------------------------------------ boot
async function main() {
  paintThemeBtn();
  $("#themeBtn").onclick = () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) { /* ignore */ }
    paintThemeBtn();
  };
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paintThemeBtn);
  $$(".tabbar button").forEach((b) => (b.onclick = () => switchTab(b.dataset.tab)));
  $("#openFilters").onclick = () => $("#filterSheet").showModal();
  $("#closeDetail").onclick = () => $("#detailSheet").close();
  for (const id of ["#filterSheet", "#detailSheet"]) {
    $(id).addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
  }
  $$("[data-cmd]").forEach((b) => (b.onclick = () => sendCommand(b.dataset.cmd)));
  $("#topic").addEventListener("change", (e) => store.set("topic", e.target.value.trim()));
  $("#histSearch").addEventListener("input", renderHistory);
  $("#historyList").addEventListener("click", (e) => { const c = e.target.closest("[data-city]"); if (c) openCityHistory(c.dataset.city); });

  if (!(await load())) { renderSettings(); return; }
  S.f = { ...defaults(), ...store.get("filters", {}) };
  buildForm(); syncForm(); wireForm();
  $("#sort").onchange = (e) => { S.f.sort = e.target.value; saveFilters(); renderTrips(); };
  $("#more").onclick = () => renderTrips(false);
  $("#results").addEventListener("click", (e) => { const c = e.target.closest(".card"); if (c) openDetail(S.trips[+c.dataset.i]); });
  $("#detailBody").addEventListener("click", (e) => { const c = e.target.closest("#othersList .card"); if (c) openDetail(S.others[+c.dataset.i]); });
  $("#priceRow").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-qp]"); if (!b) return;
    S.f.pmax = b.dataset.qp; saveFilters(); syncForm(); renderTrips();
  });
  let pt;
  $("#priceRow").addEventListener("input", (e) => {
    if (e.target.id !== "customPrice") return;
    clearTimeout(pt);
    pt = setTimeout(() => { S.f.pmax = e.target.value; e.target.parentElement.classList.toggle("on", !!e.target.value); saveFilters(); syncForm(); renderTrips(); }, 300);
  });
  $("#priceRow").addEventListener("focusout", () => setTimeout(renderPriceRow, 0));
  $("#destSelect").onchange = (e) => { S.f.dest = e.target.value; if (S.f.dest) S.f.perCity = false; else S.f.perCity = true; saveFilters(); syncForm(); renderTrips(); };
  renderTrips();
  openFromHash();
  addEventListener("hashchange", openFromHash);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(); });
  addEventListener("pageshow", (e) => { if (e.persisted) refresh(); });
  setInterval(() => refresh(true), 10 * 60000);
  setInterval(paintUpdated, 60000);
  $("#refreshBtn").onclick = () => refresh(true);
}
main();
