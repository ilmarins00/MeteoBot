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
  foce: [44.124363, 9.798269, 'Foce'],
  centro: [44.105130, 9.823554, 'Centro'],
  migliarina: [44.118279, 9.840946, 'Migliarina'],
  felettino: [44.131810, 9.845865, 'Felettino'],
  santo_stefano_magra: [44.160668, 9.915821, 'Santo Stefano di Magra'],
  sarzana: [44.112775, 9.960461, 'Sarzana'],
  marinella_sarzana: [44.048771, 10.010244, 'Marinella di Sarzana'],
  riomaggiore: [44.100119, 9.737493, 'Riomaggiore'],
  ricco_del_golfo: [44.154869, 9.764319, 'Riccò del Golfo'],
  lerici: [44.076588, 9.913639, 'Lerici'],
  portovenere: [44.054367, 9.837378, 'Portovenere'],
  le_grazie: [44.066651, 9.835905, 'Le Grazie'],
  marola: [44.091753, 9.819317, 'Marola'],
  marina_di_carrara: [44.034886, 10.044428, 'Marina di Carrara'],
  ceparana: [44.169025, 9.885630, 'Ceparana'],
  aulla: [44.213917, 9.968351, 'Aulla']
};
const LA_SPEZIA_CENTER = [44.12, 9.87];

const WEATHER_SCENES = [
  ['Cielo sereno', 'https://images.unsplash.com/photo-1499346030926-9a72daac6c63?auto=format&fit=crop&w=2200&q=85'],
  ['Cielo prevalentemente sereno', 'https://images.unsplash.com/photo-1500534623283-312aade485b7?auto=format&fit=crop&w=2200&q=85'],
  ['Cielo con nubi sparse', 'https://images.unsplash.com/photo-1534088568595-a066f410bcda?auto=format&fit=crop&w=2200&q=85'],
  ['Cielo prevalentemente nuvoloso', 'https://images.unsplash.com/photo-1534088568595-a066f410bcda?auto=format&fit=crop&w=2200&q=85'],
  ['Nuvoloso', 'https://images.unsplash.com/photo-1515694346937-94d85e41e6f0?auto=format&fit=crop&w=2200&q=85'],
  ['Coperto', 'https://images.unsplash.com/photo-1534274988757-a28bf1a57c17?auto=format&fit=crop&w=2200&q=85'],
  ['Coperto e pioggia', 'https://images.unsplash.com/photo-1519692933481-e162a57d6721?auto=format&fit=crop&w=2200&q=85'],
  ['Coperto e temporali', 'https://images.unsplash.com/photo-1605727216801-e27ce1d0a371?auto=format&fit=crop&w=2200&q=85'],
  ['Coperto e temporali forti', 'https://images.unsplash.com/photo-1561485132-59468cd0b553?auto=format&fit=crop&w=2200&q=85'],
  ['Nubi sparse e pioggia', 'https://images.unsplash.com/photo-1534274988757-a28bf1a57c17?auto=format&fit=crop&w=2200&q=85'],
  ['Nubi sparse e temporali', 'https://images.unsplash.com/photo-1605727216801-e27ce1d0a371?auto=format&fit=crop&w=2200&q=85'],
  ['Nubi sparse e temporali forti', 'https://images.unsplash.com/photo-1561485132-59468cd0b553?auto=format&fit=crop&w=2200&q=85'],
  ['Foschia', 'https://images.unsplash.com/photo-1487621167305-5d248087c724?auto=format&fit=crop&w=2200&q=85'],
  ['Nebbia', 'https://images.unsplash.com/photo-1485236715568-ddc5ee6ca227?auto=format&fit=crop&w=2200&q=85'],
  ['Nuvole basse', 'https://images.unsplash.com/photo-1536244636800-a3f74db0f3f2?auto=format&fit=crop&w=2200&q=85'],
  ['Nubi sparse e nevischio', 'https://images.unsplash.com/photo-1483664852095-d6cc6870702d?auto=format&fit=crop&w=2200&q=85'],
  ['Nubi sparse e neve', 'https://images.unsplash.com/photo-1491002052546-bf38f186af56?auto=format&fit=crop&w=2200&q=85'],
  ['Coperto e nevischio', 'https://images.unsplash.com/photo-1457269449834-928af64c684d?auto=format&fit=crop&w=2200&q=85'],
  ['Coperto e neve', 'https://images.unsplash.com/photo-1511131341194-24e2eeeebb09?auto=format&fit=crop&w=2200&q=85'],
  ['Coperto e neve intensa', 'https://images.unsplash.com/photo-1517299321609-52687d1bc55a?auto=format&fit=crop&w=2200&q=85'],
  ['Coperto e temporale di neve', 'https://images.unsplash.com/photo-1548777123-5b7f4b6b0f5c?auto=format&fit=crop&w=2200&q=85'],
  ['Nubi sparse e pioggia/neve', 'https://images.unsplash.com/photo-1516715094483-75da7dee9758?auto=format&fit=crop&w=2200&q=85'],
  ['Coperto e pioggia/neve', 'https://images.unsplash.com/photo-1485594050903-8e8ee2b071c0?auto=format&fit=crop&w=2200&q=85']
];

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
}

function renderAll(forecast, days = null) {
  const dayMap = days || { oggi: forecast };
  currentDays = dayMap;
  const generated = SITE_DATA.generated_at || forecast.meta?.generated_at;
  document.getElementById('data-update').textContent = generated ? `Dati ricevuti ${new Date(generated).toLocaleString('it-IT')}` : 'Dati ricevuti non disponibili';
  renderCurrent(forecast);
  renderRiskPanel(dayMap);
  renderHourly(forecast.hourly, dayMap);
  renderCharts(dayMap.oggi?.hourly || forecast.hourly || []);
  renderHazards(forecast.hazards);
  renderAIBox(forecast);
  renderTechnical(forecast.technical, forecast.hourly);
  applyTheme(forecast.current?.model_alert_level || forecast.current?.alert_level, forecast.current?.wmo_code, forecast.hourly);
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
  document.getElementById('current-conditions').innerHTML = `<div class="section-kicker">Situazione attuale</div><div class="current-grid"><div class="temperature-block"><p class="weather-symbol">${wmoIcon(c.wmo_code, c)}</p><p class="${tempClass}">${tempStr}°</p><p class="condition-name">${wmoLabel(c.wmo_code, c)}</p></div><div class="current-details"><p>Min <strong>${fmt(c.temp_min_c, 0)}°</strong> / Max <strong>${fmt(c.temp_max_c, 0)}°</strong></p><p>Vento <strong>${fmt(c.wind_kmh, 0)} km/h</strong> · raffiche <strong>${fmt(c.wind_gust_kmh, 0)} km/h</strong></p><div class="status-key"><span class="status-dot ${c.alert_level || 'unknown'}"></span><span>${officialLabel}<small>Fonte ufficiale: <a href="${officialUrl}" target="_blank" rel="noopener">AllertaLiguria / ARPAL</a></small></span></div><div class="status-key"><span class="status-dot score"></span><span>Indice modello: <strong>${(c.livello_attenzione || 'non disponibile').toUpperCase()}</strong><small>Non è un'allerta di protezione civile</small></span></div></div></div>`;
}

function severita(wmo) { if (wmo == null) return -1; if ([95,96,99].includes(wmo)) return 5; if ([80,81,82,65,67].includes(wmo)) return 4; if ([61,63,66].includes(wmo)) return 3; if ([51,53,55,71,73,75].includes(wmo)) return 2; if (wmo >= 45) return 1; return 0; }

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

function renderRiskPanel(days) {
  const el = document.getElementById('risk-panel');
  const labels = { oggi: 'Oggi', domani: 'Domani', dopodomani: 'Dopodomani' };
  const entries = Object.entries(labels).filter(([key]) => days?.[key]?.risk_panel && Object.keys(days[key].risk_panel).length);
  if (!entries.length) { el.innerHTML = ''; return; }
  const levels = { Trascurabile: 'basso', Marginale: 'medio', Moderato: 'medio', Elevato: 'alto', Estremo: 'estremo' };
  el.innerHTML = `<div class="section-kicker">Rischi stimati</div><h2>Quanto è probabile un fenomeno?</h2><div class="risk-day-tabs">${entries.map(([key, label], index) => `<button data-risk-day="${key}" class="risk-tab ${index === 0 ? 'active' : ''}" onclick="selectRiskDay('${key}')">${label}</button>`).join('')}</div>${entries.map(([key, label], index) => `<div class="risk-day-panel ${index === 0 ? 'active' : ''}" data-risk-day="${key}"><div class="risk-list">${Object.entries(days[key].risk_panel).map(([name, level]) => `<div class="risk-row"><span>${escapeHTML(name)}</span><strong class="risk-level ${levels[level] || 'basso'}">${escapeHTML(level)}</strong></div>`).join('')}</div></div>`).join('')}<p class="muted">Questi livelli sono una stima modellistica e non sostituiscono le allerte ufficiali.</p>`;
}

function selectRiskDay(day) { document.querySelectorAll('.risk-tab').forEach(button => button.classList.toggle('active', button.dataset.riskDay === day)); document.querySelectorAll('.risk-day-panel').forEach(panel => panel.classList.toggle('active', panel.dataset.riskDay === day)); }

function renderHourly(hourly, days) {
  const container = document.getElementById('hourly-forecast');
  const labels = { oggi: 'Oggi', domani: 'Domani', dopodomani: 'Dopodomani' };
  const dayEntries = Object.entries(days || { oggi: { hourly: hourly || [] } });
  container.innerHTML = `<div class="section-kicker">Previsione oraria</div><div class="section-heading"><h2>Le prossime giornate</h2><span class="muted">Scorri le schede per cambiare giornata</span></div><div class="day-tabs">${Object.entries(labels).map(([key, label], index) => `<button data-day="${key}" class="day-tab ${index === 0 ? 'active' : ''}" onclick="selectDay('${key}')">${label}</button>`).join('')}</div><div id="day-panels">${dayEntries.map(([key, day], index) => `<div class="day-panel ${index === 0 ? 'active' : ''}" data-day="${key}"><div class="day-date">${escapeHTML(day.meta?.date || '')}</div>${day.hourly?.length ? `<div class="hourly-scroll">${day.hourly.map((h, hIdx) => `<div class="hour-card"><strong>${h.time || '--'}</strong><span class="hour-icon">${wmoIcon(h.wmo_code, h)}</span><b>${fmt(h.T ?? h.temp_c, 0)}°</b><small>${wmoLabel(h.wmo_code, h)}</small><small>${h.precip > 0 ? fmt(h.precip, 1) + ' mm' : 'asciutto'}</small><small>raff. ${fmt(h.wind_gust, 0)} km/h</small><button class="hour-detail-btn" onclick="showHourDetail('${key}', ${hIdx})">Dettagli ▸</button></div>`).join('')}</div>` : '<p class="muted">Dati orari non disponibili per questa giornata.</p>'}</div>`).join('')}</div>`;
}

function selectDay(day) { document.querySelectorAll('.day-tab').forEach(button => button.classList.toggle('active', button.dataset.day === day)); document.querySelectorAll('.day-panel').forEach(panel => panel.classList.toggle('active', panel.dataset.day === day)); if (currentDays?.[day]?.hourly) renderCharts(currentDays[day].hourly); }

function renderZoneMap() {
  const mapElement = document.getElementById('zone-map');
  if (!mapElement || !window.L || zoneMap) return;
  zoneMap = L.map(mapElement, { scrollWheelZoom: false }).setView(LA_SPEZIA_CENTER, 10);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap' }).addTo(zoneMap);
  const markers = Object.entries(ZONE_COORDS).map(([id, location]) =>
    L.marker(location.slice(0, 2)).addTo(zoneMap).bindTooltip(location[2]).on('click', () => selectZone(id))
  );
  if (markers.length) zoneMap.fitBounds(L.featureGroup(markers).getBounds().pad(0.15));
}

// ── Radar (RainViewer) + fulmini (Blitzortung, via monitor_fulmini.py) ──
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

  try {
    const res = await fetch('lightning_data.json?t=' + Date.now());
    if (res.ok) {
      const data = await res.json();
      renderLightningMarkers(data.strikes || []);
    }
  } catch (error) {
    // File non ancora presente finché il monitor fulmini non ha girato la prima volta.
  }

  const updatedEl = document.getElementById('radar-updated');
  if (updatedEl) updatedEl.textContent = 'Aggiornato alle ' + new Date().toLocaleTimeString('it-IT');
}

function renderLightningMarkers(strikes) {
  if (!lightningLayerGroup) return;
  lightningLayerGroup.clearLayers();
  const legendEl = document.getElementById('radar-legend-count');
  if (legendEl) legendEl.textContent = strikes.length ? `${strikes.length} fulmini rilevati nella finestra` : 'Nessun fulmine rilevato nella finestra recente';
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

function renderCharts(hourly) {
  const el = document.getElementById('charts-panel');
  if (!el) return;
  if (!hourly?.length) { el.innerHTML = '<div class="section-kicker">Andamento orario</div><h2>Grafici</h2><p class="muted">Dati orari non disponibili.</p>'; return; }
  const times = hourly.map(h => h.time);
  const basic = `<div class="chart-grid">
    <div class="chart-block"><h4>Temperatura</h4><small class="chart-meta muted">°C</small>${svgLineChart(hourly.map(h => h.T), times, { unit: '°C' })}</div>
    <div class="chart-block"><h4>Pioggia oraria</h4><small class="chart-meta muted">mm/h</small>${svgBarChart(hourly.map(h => h.precip), times, { unit: 'mm' })}</div>
    <div class="chart-block"><h4>Nuvolosità</h4><small class="chart-meta muted">% copertura</small>${svgLineChart(hourly.map(h => h.cloud), times, { unit: '%', decimals: 0 })}</div>
    <div class="chart-block"><h4>Vento e raffiche</h4><small class="chart-meta muted">km/h</small>${svgLineChart(hourly.map(h => h.wind_gust), times, { unit: ' km/h', decimals: 0 })}</div>
  </div>`;
  const advanced = `<div class="chart-grid">
    <div class="chart-block"><h4>CAPE</h4><small class="chart-meta muted">J/kg — energia disponibile per i temporali</small>${svgLineChart(hourly.map(h => h.CAPE), times, { unit: ' J/kg', decimals: 0 })}</div>
    <div class="chart-block"><h4>CIN</h4><small class="chart-meta muted">J/kg — inibizione della convezione</small>${svgLineChart(hourly.map(h => h.CIN), times, { unit: ' J/kg', decimals: 0 })}</div>
    <div class="chart-block"><h4>Shear 0-6 km</h4><small class="chart-meta muted">kt — organizzazione dei temporali</small>${svgLineChart(hourly.map(h => h.shear), times, { unit: ' kt', decimals: 0 })}</div>
    <div class="chart-block"><h4>SRH 0-3 km</h4><small class="chart-meta muted">m²/s² — rotazione</small>${svgLineChart(hourly.map(h => h.SRH), times, { decimals: 0 })}</div>
    <div class="chart-block"><h4>PWAT</h4><small class="chart-meta muted">mm — acqua precipitabile</small>${svgLineChart(hourly.map(h => h.PWAT), times, { unit: ' mm', decimals: 0 })}</div>
    <div class="chart-block"><h4>DCAPE</h4><small class="chart-meta muted">J/kg — potenziale raffiche da downburst</small>${svgLineChart(hourly.map(h => h.DCAPE), times, { unit: ' J/kg', decimals: 0 })}</div>
    <div class="chart-block"><h4>SCP</h4><small class="chart-meta muted">indice composito supercelle</small>${svgLineChart(hourly.map(h => h.SCP), times, { decimals: 2 })}</div>
  </div>`;
  el.innerHTML = `<div class="section-kicker">Andamento orario</div><div class="section-heading"><h2>Grafici</h2><span class="muted">${hourly.length} ore</span></div><div class="mode-tabs"><button class="mode-tab ${chartMode === 'base' ? 'active' : ''}" onclick="selectChartMode('base')">Base</button><button class="mode-tab ${chartMode === 'avanzata' ? 'active' : ''}" onclick="selectChartMode('avanzata')">Avanzata (CAPE, CIN...)</button></div><div id="chart-mode-content">${chartMode === 'avanzata' ? advanced : basic}</div>`;
}

function selectChartMode(mode) {
  chartMode = mode;
  const activeDayKey = document.querySelector('.day-tab.active')?.dataset.day || 'oggi';
  renderCharts(currentDays?.[activeDayKey]?.hourly);
}

// ── Analisi/Momenti salienti: mostra il testo AI se disponibile, altrimenti
// una timeline calcolata dai dati (sempre presente, mai una scatola vuota) ──
function renderAIBox(forecast) {
  const el = document.getElementById('ai-analysis');
  const highlights = forecast.highlights || [];
  const highlightsHtml = highlights.length
    ? `<ul class="highlights-list">${highlights.map(ev => `<li><time>${escapeHTML(ev.time || '--')}</time><span>${escapeHTML(ev.label)}</span></li>`).join('')}</ul>`
    : '<p class="muted">Nessun momento particolarmente significativo individuato per questa giornata.</p>';
  const aiHtml = forecast.ai_analysis ? `<p class="ai-text">${escapeHTML(forecast.ai_analysis)}</p>` : '';
  const insights = forecast.insights || [];
  const insightsHtml = insights.length
    ? `<h3>Approfondimenti</h3><ul class="insights-list">${insights.map(i => `<li><strong>${escapeHTML(i.label)}:</strong> ${escapeHTML(i.text)}</li>`).join('')}</ul>`
    : '';
  el.innerHTML = `<div class="section-kicker">Lettura della giornata</div><h2>Momenti salienti</h2>${aiHtml}${highlightsHtml}${insightsHtml}`;
}

function renderHazards(hazards) { const el = document.getElementById('hazards-panel'); el.innerHTML = `<div class="section-kicker">Fenomeni severi</div><h2>Ci sono fenomeni in atto?</h2>${hazards?.reali?.length || hazards?.potenziali?.length ? `<ul>${[...(hazards.reali || []), ...(hazards.potenziali || [])].map(h => `<li>${escapeHTML(h)}</li>`).join('')}</ul>` : '<p class="safe-message">Nessun fenomeno severo rilevato.</p>'}`; }

function renderTechnical(tech, hourly) {
  const el = document.getElementById('technical-data');
  const rows = tech && typeof tech === 'object' ? Object.entries(tech).map(([key, value]) => `<tr><td>${escapeHTML(key)}</td><td>${typeof value === 'number' ? value.toFixed(1) : escapeHTML(String(value ?? 'n.d.'))}</td></tr>`).join('') : '';
  const evolution = (hourly || []).map(h => `<div class="technical-hour"><strong>${h.time || '--'}</strong><span>T ${fmt(h.T, 1)}°</span><span>RH ${fmt(h.RH, 0)}%</span><span>Vento ${fmt(h.wind, 1)}</span><span>Dir ${fmt(h.wind_dir, 0)}°</span><span>Raff. ${fmt(h.wind_gust, 1)}</span><span>Pioggia ${fmt(h.precip, 1)}</span><span>CAPE ${fmt(h.CAPE, 0)}</span><span>CIN ${fmt(h.CIN, 0)}</span><span>Shear ${fmt(h.shear, 1)}</span><span>SRH ${fmt(h.SRH, 0)}</span><span>PWAT ${fmt(h.PWAT, 1)}</span><span>DCAPE ${fmt(h.DCAPE, 0)}</span><span>SCP ${fmt(h.SCP, 2)}</span></div>`).join('');
  el.innerHTML = `<div class="technical-columns"><div><h3>Valori di riferimento</h3>${rows ? `<table>${rows}</table>` : '<p class="muted">Dati tecnici puntuali non disponibili.</p>'}</div><div><h3>Evoluzione ora per ora</h3><div class="technical-scroll">${evolution || '<p class="muted">Evoluzione non disponibile.</p>'}</div></div></div>`;
}

function toggleTechnical() { const el = document.getElementById('technical-data'); const button = document.querySelector('#technical-toggle button'); el.hidden = !el.hidden; button.textContent = el.hidden ? 'Mostra analisi tecnica' : 'Nascondi analisi tecnica'; }
function sceneFor(hourly) { const h = (hourly || []).reduce((peak, item) => severita(item.wmo_code) > severita(peak.wmo_code) ? item : peak, hourly?.[0] || {}); const code = h.wmo_code || 0; const snow = [71,73,75,85,86].includes(code); const storm = [95,96,99].includes(code); const rain = code >= 51 && code <= 82; if (snow && rain) return 21; if (snow) return code >= 75 ? 19 : 16; if (storm) return severita(code) >= 5 ? 8 : 7; if (rain) return code >= 65 ? 6 : 9; if (code >= 45) return code === 45 ? 13 : 14; return Math.min(code + 1, 5); }
function applyTheme(alertLevel, wmoCode, hourly) { const index = sceneFor(hourly); const scene = WEATHER_SCENES[index]; document.body.dataset.theme = alertLevel === 'rossa' || alertLevel === 'arancione' ? 'maltempo' : wmoCode >= 51 ? 'nuvoloso' : 'sereno'; document.documentElement.style.setProperty('--weather-image', `url("${scene[1]}")`); document.getElementById('scene-label').textContent = scene[0]; }
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
  ['CAPE',       'CAPE (energia convettiva)',   v => fmt(v, 0) + ' J/kg'],
  ['CIN',        'CIN (inibizione)',            v => fmt(v, 0) + ' J/kg'],
  ['LI',         'Lifted Index',                v => fmt(v, 1)],
  ['shear',      'Shear 0-6 km',                v => fmt(v, 1) + ' kt'],
  ['shear_0_1',  'Shear 0-1 km',                v => fmt(v, 1) + ' kt'],
  ['shear_0_3',  'Shear 0-3 km',                v => fmt(v, 1) + ' kt'],
  ['SRH',        'SRH 0-3 km',                  v => fmt(v, 0) + ' m²/s²'],
  ['srh_0_1',    'SRH 0-1 km',                  v => fmt(v, 0) + ' m²/s²'],
  ['PWAT',       'Acqua precipitabile (PWAT)',  v => fmt(v, 1) + ' mm'],
  ['KI',         'K-Index',                     v => fmt(v, 0)],
  ['TT',         'Totals-Totals',               v => fmt(v, 0)],
  ['DCAPE',      'DCAPE (potenziale downburst)',v => fmt(v, 0) + ' J/kg'],
  ['SCP',        'Supercell Composite (SCP)',   v => fmt(v, 2)],
];

function showHourDetail(dayKey, hourIndex) {
  const day = currentDays?.[dayKey];
  const h = day?.hourly?.[hourIndex];
  const modal = document.getElementById('hour-detail-modal');
  const body = document.getElementById('hour-detail-body');
  if (!h || !modal || !body) return;
  const labels = { oggi: 'Oggi', domani: 'Domani', dopodomani: 'Dopodomani' };
  const dateTxt = day?.meta?.date ? ` — ${day.meta.date}` : '';
  document.getElementById('hour-detail-title').textContent = `${labels[dayKey] || dayKey}${dateTxt} · ore ${h.time || ''}`;
  body.innerHTML = HOUR_DETAIL_FIELDS
    .filter(([key]) => h[key] !== undefined)
    .map(([key, label, fmtFn]) => `<tr><td>${escapeHTML(label)}</td><td>${escapeHTML(String(fmtFn(h[key], h)))}</td></tr>`)
    .join('');
  modal.hidden = false;
}

function closeHourDetail() {
  const modal = document.getElementById('hour-detail-modal');
  if (modal) modal.hidden = true;
}