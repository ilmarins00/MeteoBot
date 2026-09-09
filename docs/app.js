let SITE_DATA = null;
let selectedZone = null;
let clockTimer = null;
let zoneMap = null;
let currentDays = null;
let chartMode = 'base';
let radarMap = null;
let radarLayer = null;
let lightningLayerGroup = null;
let radarRefreshTimer = null;
let midnightTimer = null;

const ZONE_COORDS = {
  foce: [44.124363, 9.798269, 'La Spezia Ovest'],
  centro: [44.105130, 9.823554, 'La Spezia Centro'],
  migliarina: [44.118279, 9.840946, 'La Spezia Est'],
  felettino: [44.131810, 9.845865, 'La Spezia Nord'],
  santo_stefano_magra: [44.160668, 9.915821, 'Santo Stefano di Magra'],
  sarzana: [44.112775, 9.960461, 'Sarzana'],
  marinella_sarzana: [44.048771, 10.010244, 'Marinella di Sarzana'],
  ricco_del_golfo: [44.154869, 9.764319, 'Riccò del Golfo'],
  lerici: [44.076588, 9.913639, 'Lerici'],
  portovenere: [44.054367, 9.837378, 'Portovenere'],
  le_grazie: [44.066651, 9.835905, 'Le Grazie'],
  marola: [44.091753, 9.819317, 'Marola'],
  ceparana: [44.169025, 9.885630, 'Ceparana']
};
const LA_SPEZIA_CENTER = [44.12, 9.87];

// Ordine e nomi delle schede giorno: le prime tre hanno un nome fisso,
// giorno 4/5 mostrano invece la data ("12 Settembre") perché sono solo
// una tendenza, non una previsione con lo stesso nome delle altre.
const DAY_KEYS = ['oggi', 'domani', 'dopodomani', 'giorno4', 'giorno5'];
const DAY_FIXED_LABELS = { oggi: 'Oggi', domani: 'Domani', dopodomani: 'Dopodomani' };
const TENDENCY_DAYS = new Set(['giorno4', 'giorno5']);
function dayTabLabel(key, days) {
  return DAY_FIXED_LABELS[key] || days?.[key]?.meta?.date || key;
}
function tendencyNoteHtml() {
  return '<p class="muted tendency-note">Attenzione: questa è solo una tendenza. La probabilità di variazioni rispetto a quanto mostrato è medio/alta, specie in contesti instabili.</p>';
}

// Sfondo a colore in base alla condizione meteo prevalente della giornata
// (non più foto): blu=sereno, grigio chiaro=nuvoloso/nebbia/foschia,
// grigio=pioggia, grigio scuro=temporali, bianco=neve.
const THEME_COLORS = {
  sereno:    { label: 'Cielo sereno',           bg: 'linear-gradient(160deg, #2f6fa0, #74bdee)' },
  nuvoloso:  { label: 'Nuvoloso / nebbia',       bg: 'linear-gradient(160deg, #7d8891, #aeb8c0)' },
  pioggia:   { label: 'Pioggia',                 bg: 'linear-gradient(160deg, #5b6670, #8b969e)' },
  temporale: { label: 'Temporali',               bg: 'linear-gradient(160deg, #383e44, #565f68)' },
  neve:      { label: 'Neve',                    bg: 'linear-gradient(160deg, #d6e0e7, #f5f8fa)' },
};

async function init() {
  try {
    const res = await fetch('site_data.json?t=' + Date.now());
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    SITE_DATA = await res.json();
    renderZoneMap();
    updateClock();
    clockTimer = setInterval(updateClock, 1000);
    scheduleMidnightRollover();
  } catch (error) {
    document.getElementById('gate-error').hidden = false;
    console.error(error);
  }
}

// Allo scoccare della mezzanotte locale, promuove i dati già pronti di
// "domani" a nuovo "oggi" (e "dopodomani" a nuovo "domani"), senza dover
// aspettare il prossimo aggiornamento di site_data.json e senza mostrare
// una pagina vuota nel frattempo.
function scheduleMidnightRollover() {
  if (midnightTimer) clearTimeout(midnightTimer);
  const now = new Date();
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 5);
  midnightTimer = setTimeout(() => {
    rolloverToNextDay();
    scheduleMidnightRollover();
  }, next.getTime() - now.getTime());
}

function rolloverToNextDay() {
  if (!currentDays?.domani) return;
  const nuovoOggi = currentDays.domani;
  const nuovoDomani = currentDays.dopodomani || currentDays.domani;
  renderAll(nuovoOggi, { oggi: nuovoOggi, domani: nuovoDomani, dopodomani: nuovoDomani });
}

function showGate() {
  document.getElementById('zone-gate').hidden = false;
  document.getElementById('site-content').hidden = true;
}

function selectZone(zoneId) {
  selectedZone = zoneId;
  const baseForecast = SITE_DATA.areas?.zones?.[zoneId];
  if (!baseForecast) {
    alert('Dati non ancora disponibili per questa zona: il sito verrà aggiornato al prossimo ciclo automatico. Riprova tra qualche minuto.');
    return;
  }
  const forecast = baseForecast.days?.oggi || baseForecast;
  document.getElementById('zone-gate').hidden = true;
  document.getElementById('site-content').hidden = false;
  document.getElementById('zone-title').textContent = `Meteo ${forecast.label || zoneId}`;
  renderAll(forecast, baseForecast.days);
  initRadarMap(...(ZONE_COORDS[zoneId] ? ZONE_COORDS[zoneId].slice(0, 2) : LA_SPEZIA_CENTER));
  checkArpalAlertPopup(baseForecast);
}

// Se ARPAL Liguria ha un'allerta attiva (gialla/arancione/rossa) per questa
// zona, avvisa subito l'utente con un popup invece di lasciarlo scoprire
// l'allerta solo scorrendo la pagina.
function checkArpalAlertPopup(baseForecast) {
  const official = baseForecast?.official_alert || {};
  const level = (official.level || '').toLowerCase();
  const modal = document.getElementById('arpal-alert-modal');
  const body = document.getElementById('arpal-alert-body');
  if (!modal || !body || !['gialla', 'arancione', 'rossa'].includes(level)) return;
  const url = official.url || 'https://allertaliguria.regione.liguria.it/allerta_protezione_civile.php';
  body.innerHTML = `<p>ARPAL ha emanato un'allerta <strong>${level.toUpperCase()}</strong> per questa zona${official.risk_types ? ` (${escapeHTML(official.risk_types)})` : ''}.</p><p>Fai attenzione: consulta il sito ufficiale per i dettagli e gli orari di validità, così puoi tenerti al sicuro.</p><p><a href="${url}" target="_blank" rel="noopener">Vai al sito ARPAL / AllertaLiguria »</a></p>`;
  modal.className = `alert-toast ${level}`;
  modal.hidden = false;
}
function closeArpalAlert() {
  const modal = document.getElementById('arpal-alert-modal');
  if (modal) modal.hidden = true;
}

function renderAll(forecast, days = null) {
  const dayMap = days || { oggi: forecast };
  currentDays = dayMap;
  renderCurrent(forecast);
  renderDayExplorer(dayMap);
  applyTheme(forecast.hourly);
}

// Elenco in linguaggio semplice delle ultime modifiche al sito, leggibile
// cliccando la scritta "Ultimo aggiornamento".
const CHANGELOG_ITEMS = [
  'Errore di visualizzazione corretto per le condizioni meteo attuali.',
];
function openChangelog() {
  const body = document.getElementById('changelog-body');
  const modal = document.getElementById('changelog-modal');
  if (!body || !modal) return;
  body.innerHTML = `<ul class="highlights-list">${CHANGELOG_ITEMS.map(item => `<li>${escapeHTML(item)}</li>`).join('')}</ul>`;
  modal.hidden = false;
}
function closeChangelog() {
  const modal = document.getElementById('changelog-modal');
  if (modal) modal.hidden = true;
}

function updateClock() {
  const el = document.getElementById('local-clock');
  if (el) el.textContent = new Intl.DateTimeFormat('it-IT', { timeZone: SITE_DATA?.timezone || 'Europe/Rome', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date());
}

function renderCurrent(forecast) {
  const c = forecast.current || {};
  const official = forecast.official_alert || {};
  const officialLabel = c.alert_source ? `${c.alert_source}: ${(c.alert_level || '').toUpperCase()}` : official.status || 'Allerta ARPAL da verificare';
  const officialUrl = official.url || 'https://allertaliguria.regione.liguria.it/allerta_protezione_civile.php';
  const tempStr = fmt(c.temp_c, 1);
  const tempClass = tempStr.replace('-', '').length >= 4 ? 'temp-big long-temp' : 'temp-big';
  document.getElementById('current-conditions').innerHTML = `<div class="section-kicker">Situazione attuale</div><div class="current-grid"><div class="temperature-block"><p class="weather-symbol">${wmoIcon(c.wmo_code, c)}</p><p class="${tempClass}">${tempStr}°</p><p class="condition-name">${wmoLabel(c.wmo_code, c)}</p></div><div class="current-details"><p>Min <strong>${fmt(c.temp_min_c, 0)}°</strong> / Max <strong>${fmt(c.temp_max_c, 0)}°</strong></p><p>Vento <strong>${fmt(c.wind_kmh, 0)} km/h</strong> · raffiche <strong>${fmt(c.wind_gust_kmh, 0)} km/h</strong></p><div class="status-key"><span class="status-dot ${c.alert_level || 'unknown'}"></span><span>${officialLabel}<small>Fonte ufficiale: <a href="${officialUrl}" target="_blank" rel="noopener">AllertaLiguria / ARPAL</a></small></span></div></div></div>`;
}

// Categoria meteo per un codice WMO, usata per decidere il colore di sfondo.
function categoryFor(wmo) {
  const code = Number(wmo) || 0;
  if ([95, 96, 99].includes(code)) return 'temporale';
  if ([71, 73, 75, 77, 85, 86].includes(code)) return 'neve';
  if ([51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82].includes(code)) return 'pioggia';
  if ([45, 48].includes(code)) return 'nuvoloso'; // nebbia/foschia
  if (code >= 2) return 'nuvoloso'; // nuvoloso/coperto
  return 'sereno'; // 0 = sereno, 1 = poco nuvoloso
}

// Trova l'indice dell'ora corrente (o la più vicina) nella lista oraria di
// "oggi": serve per giudicare il meteo di ADESSO, non la media dell'intera
// giornata (altrimenti un temporale in corso nel pomeriggio resterebbe
// "nascosto" dietro ore di sole al mattino o alla sera).
function currentHourIndex(list, timezone) {
  const nowHour = new Intl.DateTimeFormat('it-IT', { timeZone: timezone || 'Europe/Rome', hour: '2-digit', hour12: false }).format(new Date()).padStart(2, '0');
  const idx = list.findIndex(h => (h.time || '').startsWith(nowHour));
  return idx >= 0 ? idx : 0;
}

// Condizione prevalente delle prossime ore (adesso + le 5 successive, non
// l'intera giornata): pioggia e temporali contano come prevalenti solo se
// coprono almeno 2 di queste ore (richiesta esplicita: un rovescio o un
// temporale isolato di un'ora non deve tingere di grigio/scuro l'intero
// sfondo del sito).
function prevalentCategory(hourly, timezone) {
  const list = hourly || [];
  if (!list.length) return 'sereno';
  const nowIdx = currentHourIndex(list, timezone);
  const window = list.slice(nowIdx, nowIdx + 6);
  const source = window.length ? window : list;
  const counts = { sereno: 0, nuvoloso: 0, pioggia: 0, temporale: 0, neve: 0 };
  source.forEach(h => { counts[categoryFor(h.wmo_code)]++; });
  const eligible = Object.entries(counts).filter(([cat, n]) => {
    if (cat === 'pioggia' || cat === 'temporale' || cat === 'neve') return n >= 2;
    return n > 0;
  });
  if (!eligible.length) return 'sereno';
  eligible.sort((a, b) => b[1] - a[1]);
  return eligible[0][0];
}

// Icona/etichetta "sole" a 7 livelli in base alla nuvolosità (totale + alta),
// usata solo per i codici WMO 0-3 (sereno/poco nuvoloso/nuvoloso/coperto):
// i fenomeni (pioggia, temporale, neve, nebbia) hanno sempre la priorità.
function skyCondition(h) {
  const cloud = h?.cloud ?? h?.cloud_pct ?? 0;
  const low = h?.cloud_low ?? h?.cloud_low_pct ?? 0;
  const mid = h?.cloud_mid ?? h?.cloud_mid_pct ?? 0;
  const high = h?.cloud_high ?? h?.cloud_high_pct ?? 0;
  const veiled = high > 25 && high >= (low + mid) && cloud < 70;
  if (cloud < 10) return veiled ? ['sole leggermente velato', '🌤️', 'icon-veil'] : ['sole pieno', '☀️', ''];
  if (cloud < 30) return veiled ? ['sole molto velato', '🌥️', 'icon-veil'] : ['sole prevalentemente pieno', '🌤️', ''];
  if (cloud < 55) return ['sole coperto a metà', '⛅', ''];
  if (cloud < 80) return ['sole quasi del tutto coperto', '🌥️', ''];
  return ['nuvoloso', '☁️', ''];
}

function wmoIcon(wmo, h) {
  if (wmo == null) return '◌';
  if ([95,96,99].includes(wmo)) return '⛈';
  if ([80,81,82,61,63,65,66,67].includes(wmo)) return '☂';
  if ([71,73,75].includes(wmo)) return '❄';
  if ([45,48].includes(wmo)) return '≋';
  if (wmo <= 3 && h) return skyCondition(h)[1];
  if (wmo >= 2) return '☁';
  return '☀';
}
function wmoLabel(wmo, h) {
  if (wmo == null) return 'n.d.';
  if ([95,96,99].includes(wmo)) return 'temporale';
  if ([80,81,82].includes(wmo)) return 'rovesci';
  if ([61,63,65,66,67].includes(wmo)) return 'pioggia';
  if ([71,73,75].includes(wmo)) return 'neve';
  if ([45,48].includes(wmo)) return 'nebbia';
  if (wmo <= 3 && h) return skyCondition(h)[0];
  if (wmo >= 2) return 'nuvoloso';
  return 'sereno';
}

// Una sola scheda giorno mostra insieme rischi, previsione oraria, grafici
// e momenti salienti di quella giornata, per evitare tab scollegati tra loro.
function renderDayExplorer(days) {
  const el = document.getElementById('day-explorer');
  const levels = { Trascurabile: 'basso', Marginale: 'medio', Moderato: 'medio', Elevato: 'alto', Estremo: 'estremo' };
  const entries = DAY_KEYS.filter(key => days?.[key]).map(key => [key, days[key]]);
  if (!entries.length) { el.innerHTML = ''; return; }

  const panelHtml = ([key, day], index) => {
    const risks = day.risk_panel && Object.keys(day.risk_panel).length
      ? `<h3>Rischi stimati</h3><div class="risk-list">${Object.entries(day.risk_panel).map(([name, level]) => `<div class="risk-row"><span>${escapeHTML(name)}</span><strong class="risk-level ${levels[level] || 'basso'}">${escapeHTML(level)}</strong></div>`).join('')}</div><p class="muted">Questi livelli sono una stima modellistica e non sostituiscono le allerte ufficiali.</p>`
      : '';
    const hourly = day.hourly?.length
      ? `<h3>Previsione oraria</h3><div class="hourly-scroll">${day.hourly.map((h, hIdx) => `<div class="hour-card"><strong>${h.time || '--'}</strong><span class="hour-icon">${wmoIcon(h.wmo_code, h)}</span><b>${fmt(h.T ?? h.temp_c, 0)}°</b><small>${wmoLabel(h.wmo_code, h)}</small><small>${h.precip > 0 ? fmt(h.precip, 1) + ' mm' : 'asciutto'}</small><small>raff. ${fmt(h.wind_gust, 0)} km/h</small><button class="hour-detail-btn" onclick="showHourDetail('${key}', ${hIdx})">Dettagli ▸</button></div>`).join('')}</div>`
      : '<h3>Previsione oraria</h3><p class="muted">Dati orari non disponibili per questa giornata.</p>';
    const charts = `<div class="section-heading"><h3>Grafici</h3><span class="muted">${day.hourly?.length || 0} ore</span></div><div class="mode-tabs">${chartModeTabsHtml()}</div><div class="chart-mode-content" data-day="${key}">${buildChartsGrid(day.hourly, chartMode)}</div>`;
    const highlights = day.highlights?.length
      ? `<h3>Momenti salienti</h3><ul class="highlights-list">${day.highlights.map(ev => `<li><time>${escapeHTML(ev.time || '--')}</time><span>${escapeHTML(ev.label)}</span></li>`).join('')}</ul>`
      : '<h3>Momenti salienti</h3><p class="muted">Nessun momento particolarmente significativo individuato per questa giornata.</p>';
    return `<div class="day-panel ${index === 0 ? 'active' : ''}" data-day="${key}"><div class="day-date">${escapeHTML(day.meta?.date || '')}</div>${TENDENCY_DAYS.has(key) ? tendencyNoteHtml() : ''}${risks}${hourly}${charts}${highlights}</div>`;
  };

  el.innerHTML = `<div class="section-kicker">Previsione giornaliera</div><div class="section-heading"><h2>Rischi, orario e grafici della giornata</h2><span class="muted">Scorri le schede per cambiare giornata</span></div><div class="day-tabs">${entries.map(([key], index) => `<button data-day="${key}" class="day-tab ${index === 0 ? 'active' : ''}" onclick="selectDay('${key}')">${dayTabLabel(key, days)}</button>`).join('')}</div><div id="day-panels">${entries.map(panelHtml).join('')}</div>`;
}

function selectDay(day) {
  document.querySelectorAll('.day-tab').forEach(button => button.classList.toggle('active', button.dataset.day === day));
  document.querySelectorAll('.day-panel').forEach(panel => panel.classList.toggle('active', panel.dataset.day === day));
}

function renderZoneMap() {
  const select = document.getElementById('zone-select');
  if (!select || select.options.length > 1) return;
  Object.entries(ZONE_COORDS).forEach(([id, location]) => {
    select.add(new Option(location[2], id));
  });
  select.addEventListener('change', event => {
    if (event.target.value) selectZone(event.target.value);
  });
}

// ── Radar (RainViewer) — fulmini (Blitzortung) attualmente disabilitati ──
// Si aggiorna da solo ogni 60 secondi finché la pagina resta aperta.
function initRadarMap(centerLat, centerLon) {
  const el = document.getElementById('radar-map');
  if (!el || !window.L) return;
  if (!radarMap) {
    radarMap = L.map(el, { scrollWheelZoom: false }).setView([centerLat, centerLon], 9);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap' }).addTo(radarMap);
    lightningLayerGroup = L.layerGroup().addTo(radarMap);
  } else {
    radarMap.setView([centerLat, centerLon], radarMap.getZoom());
  }
  refreshRadarAndLightning();
  if (!radarRefreshTimer) radarRefreshTimer = setInterval(refreshRadarAndLightning, 60000);
}

async function refreshRadarAndLightning() {
  if (!radarMap) return;
  try {
    const res = await fetch('https://api.rainviewer.com/public/weather-maps.json?t=' + Date.now());
    const data = await res.json();
    const frames = data?.radar?.past || [];
    const latest = frames[frames.length - 1];
    if (latest) {
      const url = `${data.host}${latest.path}/256/{z}/{x}/{y}/4/1_1.png`;
      if (radarLayer) radarMap.removeLayer(radarLayer);
      // RainViewer non genera tile oltre lo zoom 7: maxNativeZoom fa sì che
      // Leaflet richieda sempre la tile allo zoom 7 e la ingrandisca, invece
      // di richiedere zoom non supportati (che restituirebbero un placeholder
      // con scritto "Zoom level not supported").
      radarLayer = L.tileLayer(url, { opacity: .65, attribution: 'RainViewer', zIndex: 5, maxNativeZoom: 7 }).addTo(radarMap);
    }
  } catch (error) {
    console.error('Radar RainViewer non disponibile', error);
  }

  // Fulminazioni attualmente disabilitate: niente fetch di lightning_data.json.

  const updatedEl = document.getElementById('radar-updated');
  if (updatedEl) updatedEl.textContent = 'Aggiornato alle ' + new Date().toLocaleTimeString('it-IT');
}

function renderLightningMarkers(strikes) {
  // Fulminazioni attualmente disabilitate: funzione non più invocata,
  // lasciata solo per una riattivazione futura senza riscrivere il rendering.
  if (!lightningLayerGroup) return;
  lightningLayerGroup.clearLayers();
  const now = Date.now();
  strikes.forEach(s => {
    const ageMin = (now - new Date(s.time).getTime()) / 60000;
    const color = ageMin <= 5 ? '#ff3b3b' : ageMin <= 15 ? '#ff9d3b' : '#f5d43b';
    L.circleMarker([s.lat, s.lon], { radius: 5, color, fillColor: color, fillOpacity: .85, weight: 1, className: 'lightning-dot' })
      .bindTooltip(`${fmt(s.distance_km, 1)} km — ${new Date(s.time).toLocaleTimeString('it-IT')}`)
      .addTo(lightningLayerGroup);
  });
}

// ── Grafici (base: pioggia/nuvolosità/vento — avanzata: CAPE/CIN/shear/ecc.) ──
// Asse X = orario, asse Y = valori con linee guida min/medio/max.
function buildAxisChart(values, times, opts = {}) {
  const type = opts.type || 'line';
  const w = 920, h = 260, padL = 52, padR = 18, padT = 18, padB = 34;
  const n = (values || []).length;
  const nums = (values || []).map(v => (v == null ? null : Number(v)));
  const valid = nums.filter(v => v != null && !isNaN(v));
  if (!n || !valid.length) return '<p class="muted">Dati non disponibili.</p>';

  let min = type === 'bar' ? 0 : Math.min(...valid);
  let max = Math.max(...valid, type === 'bar' ? 1 : -Infinity);
  if (min === max) { min -= 1; max += 1; }
  const range = max - min;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const stepX = innerW / Math.max(n - 1, 1);
  const scaleY = v => padT + innerH - ((v - min) / range) * innerH;

  const ticks = [max, min + range / 2, min];
  const gridHtml = ticks.map(t => {
    const y = scaleY(t);
    return `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${w - padR}" y2="${y.toFixed(1)}" class="chart-grid-line"></line>` +
           `<text x="${padL - 8}" y="${(y + 4).toFixed(1)}" class="chart-axis-label" text-anchor="end">${fmt(t, opts.decimals ?? 1)}${opts.unit || ''}</text>`;
  }).join('');

  const labelEvery = Math.max(Math.ceil(n / 8), 1);
  const xLabelsHtml = (times || []).map((t, i) => {
    if (i % labelEvery !== 0 && i !== n - 1) return '';
    const x = padL + i * stepX;
    return `<text x="${x.toFixed(1)}" y="${h - 10}" class="chart-axis-label" text-anchor="middle">${escapeHTML(t || '')}</text>`;
  }).join('');

  let body = '';
  if (type === 'bar') {
    const barW = innerW / n;
    body = nums.map((v, i) => {
      if (v == null) return '';
      const x = padL + i * barW + barW * 0.15;
      const y = scaleY(v);
      const bh = (padT + innerH) - y;
      return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(barW * 0.7).toFixed(1)}" height="${Math.max(bh, 0).toFixed(1)}" rx="2" class="chart-bar"></rect>`;
    }).join('');
  } else {
    let line = '', started = false;
    const pts = [];
    nums.forEach((v, i) => {
      const x = padL + i * stepX;
      if (v == null) { started = false; return; }
      const y = scaleY(v);
      pts.push([x, y]);
      line += (started ? 'L' : 'M') + x.toFixed(1) + ',' + y.toFixed(1) + ' ';
      started = true;
    });
    if (pts.length) {
      const area = line + `L${pts[pts.length - 1][0].toFixed(1)},${padT + innerH} L${pts[0][0].toFixed(1)},${padT + innerH} Z`;
      const dots = pts.map(([x, y]) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.6" class="chart-dot"></circle>`).join('');
      body = `<path d="${area}" class="chart-area"></path><path d="${line}" class="chart-line"></path>${dots}`;
    }
  }
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" class="chart-svg">${gridHtml}${body}${xLabelsHtml}</svg>`;
}

function svgLineChart(values, times, opts = {}) { return buildAxisChart(values, times, { ...opts, type: 'line' }); }
function svgBarChart(values, times, opts = {}) { return buildAxisChart(values, times, { ...opts, type: 'bar' }); }

function chartModeTabsHtml() {
  return `<button class="mode-tab ${chartMode === 'base' ? 'active' : ''}" onclick="selectChartMode('base')">Base</button><button class="mode-tab ${chartMode === 'avanzata' ? 'active' : ''}" onclick="selectChartMode('avanzata')">Avanzata (CAPE, CIN...)</button>`;
}

function buildChartsGrid(hourly, mode) {
  if (!hourly?.length) return '<p class="muted">Dati orari non disponibili.</p>';
  const times = hourly.map(h => h.time);
  if (mode === 'avanzata') {
    return `<div class="chart-grid">
    <div class="chart-block"><h4>CAPE</h4><small class="chart-meta muted">J/kg — energia disponibile per i temporali</small>${svgLineChart(hourly.map(h => h.SBCAPE ?? h.MUCAPE), times, { unit: ' J/kg', decimals: 0 })}</div>
    <div class="chart-block"><h4>CIN</h4><small class="chart-meta muted">J/kg — inibizione della convezione</small>${svgLineChart(hourly.map(h => h.CIN), times, { unit: ' J/kg', decimals: 0 })}</div>
    <div class="chart-block"><h4>Shear 0-6 km</h4><small class="chart-meta muted">kt — organizzazione dei temporali</small>${svgLineChart(hourly.map(h => h.shear), times, { unit: ' kt', decimals: 0 })}</div>
    <div class="chart-block"><h4>SRH 0-3 km</h4><small class="chart-meta muted">m²/s² — rotazione</small>${svgLineChart(hourly.map(h => h.SRH), times, { decimals: 0 })}</div>
    <div class="chart-block"><h4>PWAT</h4><small class="chart-meta muted">mm — acqua precipitabile</small>${svgLineChart(hourly.map(h => h.PWAT), times, { unit: ' mm', decimals: 0 })}</div>
    <div class="chart-block"><h4>DCAPE</h4><small class="chart-meta muted">J/kg — potenziale raffiche da downburst</small>${svgLineChart(hourly.map(h => h.DCAPE), times, { unit: ' J/kg', decimals: 0 })}</div>
    <div class="chart-block"><h4>SCP</h4><small class="chart-meta muted">indice composito supercelle</small>${svgLineChart(hourly.map(h => h.SCP), times, { decimals: 2 })}</div>
  </div>`;
  }
  return `<div class="chart-grid">
    <div class="chart-block"><h4>Temperatura</h4><small class="chart-meta muted">°C</small>${svgLineChart(hourly.map(h => h.T), times, { unit: '°C' })}</div>
    <div class="chart-block"><h4>Pioggia oraria</h4><small class="chart-meta muted">mm/h</small>${svgBarChart(hourly.map(h => h.precip), times, { unit: 'mm' })}</div>
    <div class="chart-block"><h4>Nuvolosità</h4><small class="chart-meta muted">% copertura</small>${svgLineChart(hourly.map(h => h.cloud), times, { unit: '%', decimals: 0 })}</div>
    <div class="chart-block"><h4>Vento e raffiche</h4><small class="chart-meta muted">km/h</small>${svgLineChart(hourly.map(h => h.wind_gust), times, { unit: ' km/h', decimals: 0 })}</div>
  </div>`;
}

// Il toggle Base/Avanzata è unico e vale per tutte le schede giorno: al
// cambio va rigenerato il grafico di ognuna, non solo di quella visibile.
function selectChartMode(mode) {
  chartMode = mode;
  document.querySelectorAll('.mode-tab').forEach(button => button.classList.toggle('active', button.textContent.trim().startsWith(mode === 'avanzata' ? 'Avanzata' : 'Base')));
  document.querySelectorAll('.chart-mode-content').forEach(container => {
    const key = container.dataset.day;
    container.innerHTML = buildChartsGrid(currentDays?.[key]?.hourly, chartMode);
  });
}
function applyTheme(hourly) {
  const cat = prevalentCategory(hourly, SITE_DATA?.timezone);
  const theme = THEME_COLORS[cat] || THEME_COLORS.sereno;
  document.body.dataset.theme = cat;
  document.documentElement.style.setProperty('--weather-bg', theme.bg);
  document.getElementById('scene-label').textContent = theme.label;
}
function fmt(value, decimals) { return value != null && !isNaN(value) ? Number(value).toFixed(decimals) : '--'; }
function escapeHTML(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char])); }

init();

// ── Dettaglio orario completo (tutti i dati tecnici) ──────────────────────
const COMPASS_16 = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSO","SO","OSO","O","ONO","NO","NNO"];
function windDirText(deg) {
  if (deg == null || isNaN(deg)) return 'n.d.';
  return COMPASS_16[Math.round((((Number(deg) % 360) + 360) % 360) / 22.5) % 16];
}

// Ordine "conveniente": prima meteo di superficie, poi cielo/precipitazioni,
// infine tutti gli indici tecnici avanzati (termodinamica, shear, indici compositi).
const HOUR_DETAIL_FIELDS = [
  ['time',       'Ora',                         v => v ?? '--'],
  ['T',          'Temperatura',                 v => fmt(v, 1) + '°C'],
  ['RH',         'Umidità relativa',            v => fmt(v, 0) + '%'],
  ['wind',       'Vento medio',                 v => fmt(v, 0) + ' km/h'],
  ['wind_dir',   'Direzione vento',             v => v != null ? `${fmt(v, 0)}° (${windDirText(v)})` : 'n.d.'],
  ['wind_gust',  'Raffica massima',             v => fmt(v, 0) + ' km/h'],
  ['precip',     'Pioggia in quest\'ora',       v => fmt(v, 1) + ' mm/h'],
  ['precip_cum', 'Pioggia cumulata dall\'inizio giornata', v => fmt(v, 1) + ' mm'],
  ['wmo_code',   'Condizione prevalente',       (v, h) => wmoLabel(v, h)],
  ['cloud',      'Nuvolosità totale',           v => fmt(v, 0) + '%'],
  ['cloud_low',  'Nuvole basse',                v => fmt(v, 0) + '%'],
  ['cloud_mid',  'Nuvole medie',                v => fmt(v, 0) + '%'],
  ['cloud_high', 'Nuvole alte',                 v => fmt(v, 0) + '%'],
  ['SBCAPE',     'SBCAPE (energia convettiva)', v => fmt(v, 0) + ' J/kg'],
  ['MUCAPE',     'MUCAPE (energia convettiva)', v => fmt(v, 0) + ' J/kg'],
  ['CIN',        'CIN (inibizione)',            v => fmt(v, 0) + ' J/kg'],
  ['LI',         'Lifted Index',                v => fmt(v, 1)],
  ['shear',      'Shear 0-6 km',                v => fmt(v, 1) + ' kt'],
  ['shear_0_1',  'Shear 0-1 km',                v => fmt(v, 1) + ' kt'],
  ['shear_0_3',  'Shear 0-3 km',                v => fmt(v, 1) + ' kt'],
  ['SRH',        'SRH 0-3 km',                  v => fmt(v, 0) + ' m²/s²'],
  ['srh_0_1',    'SRH 0-1 km',                  v => fmt(v, 0) + ' m²/s²'],
  ['PWAT',       'Acqua precipitabile (PWAT)',  v => fmt(v, 1) + ' mm'],
  ['DCAPE',      'DCAPE (potenziale downburst)',v => fmt(v, 0) + ' J/kg'],
  ['STP',        'Significant Tornado Parameter (STP)', v => fmt(v, 2)],
  ['KI',         'K-Index',                     v => fmt(v, 0)],
  ['TT',         'Totals-Totals',               v => fmt(v, 0)],
  ['SCP',        'Supercell Composite (SCP)',   v => fmt(v, 2)],
];

function showHourDetail(dayKey, hourIndex) {
  const day = currentDays?.[dayKey];
  const h = day?.hourly?.[hourIndex];
  const modal = document.getElementById('hour-detail-modal');
  const body = document.getElementById('hour-detail-body');
  if (!h || !modal || !body) return;
  const dateTxt = day?.meta?.date ? ` — ${day.meta.date}` : '';
  const detailHour = {
    ...h,
    SBCAPE: h.SBCAPE ?? h.CAPE,
    MUCAPE: h.MUCAPE ?? h.SBCAPE ?? h.CAPE,
    KI: h.KI ?? null,
    TT: h.TT ?? null,
  };
  document.getElementById('hour-detail-title').textContent = `${dayTabLabel(dayKey, currentDays)}${dateTxt} · ore ${h.time || ''}`;
  body.innerHTML = HOUR_DETAIL_FIELDS
    .filter(([key]) => detailHour[key] !== undefined)
    .map(([key, label, fmtFn]) => `<tr><td>${escapeHTML(label)}</td><td>${escapeHTML(String(fmtFn(detailHour[key], detailHour)))}</td></tr>`)
    .join('');
  modal.hidden = false;
}

function closeHourDetail() {
  const modal = document.getElementById('hour-detail-modal');
  if (modal) modal.hidden = true;
}