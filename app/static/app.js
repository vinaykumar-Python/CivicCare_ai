const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let token = localStorage.getItem('cc_token');
let user = JSON.parse(localStorage.getItem('cc_user') || 'null');
let map = null;
let mapLayers = [];

const esc = (x) => String(x ?? '').replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

async function api(url, opt = {}) {
  opt.headers = {...(opt.headers || {}), ...(token ? {Authorization: `Bearer ${token}`} : {})};
  const response = await fetch(url, opt);
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(data.detail || data.message || `Request failed (${response.status})`);
  return data;
}

function toast(message) {
  $('#toast').innerHTML = `<div class="toast">${esc(message)}</div>`;
  setTimeout(() => { $('#toast').innerHTML = ''; }, 3200);
}

function setUser(u) {
  user = u;
  const initial = (u?.name || 'C')[0].toUpperCase();
  $('#userName').textContent = u?.name || 'Citizen';
  $('#topName').textContent = u?.name || 'Citizen';
  $('#userAvatar').textContent = initial;
  $('#topAvatar').textContent = initial;
  const role = u?.role || 'citizen';
  const authority = role === 'authority';
  const admin = role === 'admin';
  $$('.citizen-only').forEach((el) => el.classList.toggle('hidden', role !== 'citizen'));
  $$('.role-authority').forEach((el) => el.classList.toggle('hidden', !authority));
  $$('.role-admin').forEach((el) => el.classList.toggle('hidden', !admin));
  $$('.staff-only').forEach((el) => el.classList.toggle('hidden', !(authority || admin)));
  $('#workspaceLabel').textContent = admin ? 'ADMINISTRATION WORKSPACE' : authority ? `${u.department || 'AUTHORITY'} WORKSPACE`.toUpperCase() : 'CITIZEN WORKSPACE';
  $('.account-mini small').textContent = admin ? 'System administration' : authority ? `${u.department || 'Authority'} operations` : 'Citizen account';
  $('.sidebar-brand').setAttribute('aria-label', role === 'citizen' ? 'Citizen workspace' : role === 'authority' ? `${u.department} authority workspace` : 'Administration workspace');
  const homeNav = document.querySelector('[data-page="home"]');
  if (homeNav) homeNav.querySelector('span:last-child').textContent = admin ? 'Admin overview' : authority ? 'Authority dashboard' : 'Home';
  const reportNav = document.querySelector('[data-page="reports"]');
  if (reportNav) reportNav.querySelector('span:last-child').textContent = 'My reports';
}

async function auth() {
  if (token && user) {
    try {
      const me = await api('/api/me');
      user = me;
      localStorage.setItem('cc_user', JSON.stringify(user));
      $('#auth').classList.add('hidden');
      $('#app').classList.remove('hidden');
      setUser(user);
      await show('home');
      return;
    } catch (_) {
      localStorage.removeItem('cc_token');
      localStorage.removeItem('cc_user');
      token = null;
      user = null;
    }
  }
  $('#auth').classList.remove('hidden');
  $('#app').classList.add('hidden');
}

$$('.auth-tabs button').forEach((button) => button.onclick = () => {
  $$('.auth-tabs button').forEach((b) => b.classList.remove('active'));
  button.classList.add('active');
  $('#loginForm').classList.toggle('hidden', button.dataset.auth !== 'login');
  $('#registerForm').classList.toggle('hidden', button.dataset.auth !== 'register');
});

function updateLoginMode() {
  const role = $('#loginRole')?.value || 'citizen';
  const authority = role === 'authority';
  $('#authoritySelector')?.classList.toggle('hidden', !authority);
  $('#demoAccess')?.classList.toggle('hidden', !authority);
  $('#loginHelp').textContent = authority ? 'Select the department you represent. Your account opens only that department workspace.' : 'Sign in to report civic issues, explore live intelligence and track your own complaints.';
  $('#loginSubmit').textContent = authority ? 'Open Authority Dashboard' : 'Continue';
}
$('#loginRole')?.addEventListener('change', updateLoginMode);
$('#authorityDepartment')?.addEventListener('change', () => {
  const map = {Roads:'roads',Traffic:'traffic',Water:'water',Sanitation:'sanitation',Electrical:'electrical','Disaster Management':'disaster',Emergency:'emergency','General Services':'general'};
  const email = map[$('#authorityDepartment').value];
  if (email) { $('#loginEmail').value = `${email}@civiccare.local`; $('#loginPassword').value = 'Authority@123'; }
});
updateLoginMode();

$$('.demo-account').forEach((button) => button.onclick = () => {
  $$('.auth-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.auth === 'login'));
  $('#loginForm').classList.remove('hidden');
  $('#registerForm').classList.add('hidden');
  $('#loginRole').value = 'authority';
  updateLoginMode();
  $('#loginForm input[name=\"email\"]').value = button.dataset.demoEmail;
  $('#loginForm input[name=\"password\"]').value = button.dataset.demoPassword;
  const dept = button.querySelector('b').textContent;
  const opt = [...$('#authorityDepartment').options].find(o => o.textContent.startsWith(dept));
  if (opt) $('#authorityDepartment').value = opt.value;
  toast(`${dept} authority credentials filled`);
});

$('#authorityPortal').onclick = () => { document.querySelector('.demo-access')?.scrollIntoView({behavior:'smooth', block:'center'}); toast('Choose the authority department you want to test'); };

function authError(message) {
  const box = $('#authError');
  if (box) { box.textContent = message; box.classList.remove('hidden'); }
  toast(message);
}

$('#loginForm').onsubmit = async (event) => {
  event.preventDefault();
  const submit = event.submitter || $('#loginSubmit');
  submit.disabled = true;
  $('#authError')?.classList.add('hidden');
  try {
    const data = await api('/api/auth/login', {method:'POST', body:new FormData(event.target)});
    token = data.token;
    user = data.user;
    localStorage.setItem('cc_token', token);
    localStorage.setItem('cc_user', JSON.stringify(user));
    await auth();
    toast(user?.role === 'authority' ? `${user.department || 'Authority'} workspace opened` : 'Welcome to CivicCare');
  } catch (error) {
    localStorage.removeItem('cc_token');
    localStorage.removeItem('cc_user');
    token = null; user = null;
    authError(error.message);
  } finally { submit.disabled = false; }
};

$('#registerForm').onsubmit = async (event) => {
  event.preventDefault();
  const submit = event.submitter || event.target.querySelector('button[type="submit"]');
  submit.disabled = true;
  $('#authError')?.classList.add('hidden');
  try {
    const data = await api('/api/auth/register', {method:'POST', body:new FormData(event.target)});
    token = data.token;
    user = data.user;
    localStorage.setItem('cc_token', token);
    localStorage.setItem('cc_user', JSON.stringify(user));
    await auth();
    toast('Your account is ready and saved to the application database');
  } catch (error) { authError(error.message); }
  finally { submit.disabled = false; }
};

$('#logout').onclick = () => {
  localStorage.removeItem('cc_token');
  localStorage.removeItem('cc_user');
  token = null;
  user = null;
  if (map) { map.remove(); map = null; }
  auth();
};

$$('.nav').forEach((button) => button.onclick = () => show(button.dataset.page));

function shell(title, html) {
  $('#pageTitle').textContent = title;
  $('#content').innerHTML = `<div class="content">${html}</div>`;
  window.scrollTo({top:0, behavior:'smooth'});
}

async function show(page) {
  $$('.nav').forEach((button) => button.classList.toggle('active', button.dataset.page === page));
  if (page === 'home') return user?.role === 'citizen' ? homePage() : authorityPage();
  if (page === 'live-map') return liveMapPage();
  if (page === 'report') return reportPage();
  if (page === 'authority-portal') return ['authority','admin'].includes(user?.role) ? authorityPortalPage() : homePage();
  if (page === 'authority') { if (!['authority','admin'].includes(user?.role)) return authorityPortalPage(); return authorityPage(); }
  if (page === 'admin-config') { if (user?.role !== 'admin') return homePage(); return adminConfigPage(); }
  return reportsPage();
}

function authorityPortalPage() {
  shell('Authority portal', `
    <section class="authority-hero"><div><span class="eyebrow">CIVICCARE AUTHORITY PORTAL</span><h2>Every complaint reaches a responsible civic team.</h2><p>Authorities sign in separately. Once a citizen submits a report, CivicCare routes it to the matching department queue. Staff can acknowledge, work, resolve or escalate it, and every action becomes visible to the citizen.</p><div class="hero-actions"><button class="primary" id="openAuthorityLogin">Authority sign in →</button></div></div><div class="authority-badge"><span>●</span><b>Protected staff area</b><small>Department-based access</small></div></section>
    <section class="section-block"><div class="section-heading"><div><span class="eyebrow">END-TO-END FLOW</span><h2>Citizen → Authority → Citizen</h2></div></div><div class="flow-grid"><div class="flow-item"><span>01</span><div><b>Citizen reports</b><p>Issue, location and evidence are submitted.</p></div></div><div class="flow-item"><span>02</span><div><b>CivicCare routes</b><p>AI determines category, priority and responsible department.</p></div></div><div class="flow-item"><span>03</span><div><b>Authority receives</b><p>The complaint appears only in the assigned department queue.</p></div></div><div class="flow-item"><span>04</span><div><b>Authority acts</b><p>Staff acknowledge, update, resolve or escalate the report.</p></div></div><div class="flow-item"><span>05</span><div><b>Citizen tracks</b><p>The citizen sees the authority, status and action timeline.</p></div></div></div></section>
    <section class="section-block"><div class="section-heading"><div><span class="eyebrow">DEPARTMENT ROUTING</span><h2>Who receives each issue?</h2></div></div><div class="two-col"><div class="panel-card"><h3>Roads</h3><p>Potholes, damaged roads and road-surface issues.</p></div><div class="panel-card"><h3>Traffic</h3><p>Traffic incidents, unsafe junctions and accident-related reports.</p></div><div class="panel-card"><h3>Water</h3><p>Water supply and related civic water complaints.</p></div><div class="panel-card"><h3>Sanitation</h3><p>Garbage, waste and sanitation issues.</p></div><div class="panel-card"><h3>Electrical</h3><p>Streetlights and electrical civic issues.</p></div><div class="panel-card"><h3>Disaster Management</h3><p>Flooding, drainage and related emergency-risk reports.</p></div></div></section>`);
  $('#openAuthorityLogin').onclick = () => {
    localStorage.removeItem('cc_token'); localStorage.removeItem('cc_user'); token=null; user=null;
    $('#app').classList.add('hidden'); $('#auth').classList.remove('hidden');
    document.querySelector('.demo-access')?.scrollIntoView({behavior:'smooth', block:'center'});
    toast('Choose an authority department to sign in');
  };
}

async function homePage() {
  shell('Public urban overview', `
    <section class="hero-card">
      <div class="hero-main">
        <span class="eyebrow">YOUR CITY, IN CONTEXT</span>
        <h2>See what is happening around you.</h2>
        <p>CivicCare combines live weather, traffic and incidents with historical accident evidence and citizen reports to help you understand an area.</p>
        <div class="hero-actions"><button class="primary" id="heroMap">Explore live map <span>→</span></button><button class="btn secondary" id="heroReport">Report an issue</button></div>
      </div>
      <div class="hero-side"><div class="hero-number">LIVE</div><div>Area intelligence</div><small>Current providers are labelled clearly. Missing live providers are never replaced with fake data.</small></div>
    </section>

    <section class="section-block">
      <div class="section-heading"><div><span class="eyebrow">AT A GLANCE</span><h2>Public civic activity</h2></div><button class="text-btn" id="refreshHome">Refresh</button></div>
      <div class="stat-grid" id="publicStats"><div class="stat-card loading-card"></div><div class="stat-card loading-card"></div><div class="stat-card loading-card"></div><div class="stat-card loading-card"></div></div>
    </section>

    <section class="section-block two-col">
      <div class="panel-card">
        <div class="section-heading"><div><span class="eyebrow">SIMPLE FLOW</span><h2>How CivicCare works</h2></div></div>
        <div class="flow-list">
          <div class="flow-item"><span>01</span><div><b>Choose an area</b><p>Search a place or click the map to evaluate the surrounding area.</p></div></div>
          <div class="flow-item"><span>02</span><div><b>Read the evidence</b><p>See live weather, traffic and incidents separately from historical accident patterns.</p></div></div>
          <div class="flow-item"><span>03</span><div><b>AI routes the report</b><p>CivicCare classifies the issue and sends it to the responsible civic department.</p></div></div>
          <div class="flow-item"><span>04</span><div><b>Authority acts</b><p>The assigned department acknowledges, updates and resolves the complaint.</p></div></div>
          <div class="flow-item"><span>05</span><div><b>Citizen tracks</b><p>Follow the status, authority updates and resolution from My Reports.</p></div></div>
        </div>
      </div>
      <div class="panel-card dark-panel">
        <div class="section-heading"><div><span class="eyebrow">DATA SOURCES</span><h2>What powers the view</h2></div></div>
        <div class="source-list">
          <div><span class="source-icon weather">☁</span><div><b>Live weather</b><small>Open-Meteo · current conditions</small></div></div>
          <div><span class="source-icon traffic">↔</span><div><b>Live traffic</b><small>TomTom · when configured</small></div></div>
          <div><span class="source-icon incident">!</span><div><b>Live incidents</b><small>TomTom · when configured</small></div></div>
          <div><span class="source-icon history">◌</span><div><b>Historical intelligence</b><small>20,000 accident records + Random Forest</small></div></div>
        </div>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading"><div><span class="eyebrow">MODEL CONTEXT</span><h2>Historical ML snapshot</h2></div><span class="quiet-badge">Not live-world accuracy</span></div>
      <div class="model-strip" id="modelSnapshot"><div><span>Records</span><b>—</b></div><div><span>R²</span><b>—</b></div><div><span>MAE</span><b>—</b></div><div><span>Model</span><b>Random Forest</b></div></div>
      <div class="model-note">These metrics describe the supplied historical accident dataset and held-out evaluation split. They are not a guarantee of future accident probability.</div>
    </section>
  `);

  $('#heroMap').onclick = () => show('live-map');
  $('#heroReport').onclick = () => show('report');
  $('#refreshHome').onclick = () => loadHomeData();
  loadHomeData();
}

async function loadHomeData() {
  try {
    const [publicData, dataset] = await Promise.all([api('/api/public/summary'), api('/api/dataset/summary')]);
    $('#publicStats').innerHTML = `
      <div class="stat-card"><span>Reports submitted</span><b>${publicData.complaints.total.toLocaleString()}</b><small>Across CivicCare</small></div>
      <div class="stat-card"><span>Open reports</span><b>${publicData.complaints.open.toLocaleString()}</b><small>Current report status</small></div>
      <div class="stat-card"><span>Resolved reports</span><b>${publicData.complaints.resolved.toLocaleString()}</b><small>Marked resolved</small></div>
      <div class="stat-card"><span>Accident records</span><b>${dataset.total_records.toLocaleString()}</b><small>Historical dataset</small></div>`;
    $('#modelSnapshot').innerHTML = `
      <div><span>Records</span><b>${dataset.total_records.toLocaleString()}</b></div>
      <div><span>R²</span><b>${dataset.model.r2}</b></div>
      <div><span>MAE</span><b>${dataset.model.mae}</b></div>
      <div><span>Model</span><b>Random Forest</b></div>`;
  } catch (error) { toast(error.message); }
}

function liveMapPage() {
  shell('Explore live map', `
    <section class="map-intro"><div><span class="eyebrow">AREA INTELLIGENCE</span><h2>Explore a location</h2><p>Search for a place or click anywhere on the map. CivicCare will evaluate the surrounding area using the available live and historical evidence.</p></div><div class="live-status"><i></i><b>LIVE-READY</b><small>Provider availability is shown below.</small></div></section>
    <div class="map-toolbar"><div class="search-box"><span>⌕</span><input id="place" placeholder="Search a place — Bengaluru, Whitefield, etc."><button id="search" class="primary">Search</button></div><div class="toolbar-actions"><button class="btn secondary" id="locate">Use my location</button><button class="btn secondary" id="refresh">Refresh</button></div></div>
    <div class="map-layout"><div class="map-card"><div id="map" class="map"></div><div class="map-footer"><div class="legend"><span class="hist">Historical accident</span><span class="traffic">Live traffic</span><span class="incident">Live incident</span><span class="report">CivicCare report</span></div><span id="lastRefresh">Select a location</span></div></div><aside class="intel-panel" id="intel"><div class="empty-intel"><span class="empty-icon">⌖</span><span class="eyebrow">READY TO EXPLORE</span><h3>Choose a point on the map</h3><p>We will show current conditions, nearby reports, historical accident evidence and the available ML context.</p><div class="notice">Live traffic and incidents require TomTom configuration. Weather uses Open-Meteo and does not require an API key.</div></div></aside></div>
  `);
  initMap();
  $('#search').onclick = searchPlace;
  $('#place').onkeydown = (e) => { if (e.key === 'Enter') searchPlace(); };
  $('#locate').onclick = locate;
  $('#refresh').onclick = () => { const c = map.getCenter(); selected(c.lat, c.lng, true); };
}

function initMap() {
  if (map) map.remove();
  map = L.map('map', {zoomControl:true}).setView([12.9716,77.5946], 11);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {attribution:'© OpenStreetMap contributors'}).addTo(map);
  map.on('click', (event) => selected(event.latlng.lat, event.latlng.lng));
  selected(12.9716, 77.5946, true);
}

function clearMapLayers() {
  mapLayers.forEach((layer) => map.removeLayer(layer));
  mapLayers = [];
}

function addLayer(layer) { layer.addTo(map); mapLayers.push(layer); return layer; }
function weatherIcon(weather) { return ({Clear:'☀️',Cloudy:'☁️',Fog:'🌫️',Rain:'🌧️',Snow:'❄️',Storm:'⛈️'}[weather] || '🌤️'); }
function weatherSeverity(weather) { return weather === 'Storm' ? 'SEVERE' : weather === 'Rain' ? 'CAUTION' : 'NORMAL'; }
function providerBadge(ok, label) { return `<span class="source-badge ${ok ? 'ok' : 'off'}"><i></i>${label}<small>${ok ? 'LIVE' : 'OFF'}</small></span>`; }

async function selected(lat, lng, center = false) {
  if (center) map.setView([lat,lng], 12);
  $('#intel').innerHTML = `<div class="loading-state"><span class="eyebrow">EVALUATING AREA</span><h3>Checking current conditions…</h3><p>Reading weather, traffic, incidents, historical evidence and nearby CivicCare reports.</p><div class="loading-bar"></div></div>`;
  try {
    const [data, mapData] = await Promise.all([
      api(`/api/live/area?latitude=${lat}&longitude=${lng}&radius_km=10`),
      api(`/api/map/issues?latitude=${lat}&longitude=${lng}&radius_km=10`)
    ]);
    clearMapLayers();
    const score = data.risk.score;
    const traffic = data.live.traffic;
    const weather = data.live.weather;
    const incidents = data.live.incidents;

    addLayer(L.circle([lat,lng], {radius:10000,color:'#2F6B4F',weight:1,fillColor:'#2F6B4F',fillOpacity:.055}));
    addLayer(L.circleMarker([lat,lng], {radius:8,color:'#fff',weight:3,fillColor:'#2F5D73',fillOpacity:1}))
      .bindPopup(`<b>${esc(data.location.display_name || 'Selected area')}</b><br>Evidence score: ${Math.round(score*100)}/100`).openPopup();

    (mapData.issues || []).forEach((item) => {
      const color = item.type === 'accident' ? '#3E6885' : item.type === 'complaint' ? '#B65C3A' : '#5E6B76';
      addLayer(L.circleMarker([item.lat,item.lng], {radius:item.type==='complaint'?6:5,color:'#fff',weight:1.4,fillColor:color,fillOpacity:.8}))
        .bindPopup(`<b>${esc(item.title)}</b><br>${esc(item.detail)}<br><small>${esc(item.source)}</small>`);
    });

    (incidents.incidents || []).forEach((item) => {
      addLayer(L.circleMarker([item.lat,item.lng], {radius:7,color:'#fff',weight:2,fillColor:'#A64040',fillOpacity:.95}))
        .bindPopup(`<b>Live traffic incident</b><br>${esc(item.description || 'Traffic incident')}<br><small>TomTom · live</small>`);
    });

    if (traffic.available) {
      addLayer(L.circleMarker([lat,lng], {radius:12,color:'#A96E1E',weight:2,fillOpacity:0,fillColor:'#A96E1E'}))
        .bindPopup(`<b>Live traffic</b><br>${esc(traffic.traffic_density)} congestion · ${traffic.current_speed_kmh} km/h`);
    }

    $('#lastRefresh').textContent = `Updated ${new Date().toLocaleTimeString()}`;
    const weatherStatus = weatherSeverity(weather.weather);
    const evidence = (data.risk.components || []).map((component) => `
      <div class="metric-row"><span>${esc(component.name)} <small>${Math.round(component.weight*100)}%</small></span><b>${Math.round(component.value*100)}/100</b></div>`).join('');

    $('#intel').innerHTML = `
      <div class="intel-top"><div><span class="eyebrow">${esc(data.location.city || 'SELECTED AREA')}</span><h3>${esc(data.location.display_name || 'Current area')}</h3><small>10 km evidence radius</small></div><span class="risk-badge ${data.risk.level}">${esc(data.risk.level)}</span></div>
      <div class="risk-block"><div><span class="label">CURRENT EVIDENCE SCORE</span><strong>${Math.round(score*100)}<small>/100</small></strong><p>Decision-support evidence, not accident probability.</p></div><div class="risk-ring" style="--score:${score*360}deg"><span>${esc(data.risk.level)}</span></div></div>
      <div class="score-bar"><i style="width:${score*100}%"></i></div>
      <div class="signal-grid">
        <div class="signal-card"><span class="signal-icon">${weatherIcon(weather.weather)}</span><div class="signal-content"><small>WEATHER</small><b>${weather.available ? esc(weather.weather) : 'Unavailable'}</b><em>${weather.available ? `${weather.temperature_c}°C · ${weather.humidity}% humidity` : 'Open-Meteo unavailable'}</em></div></div>
        <div class="signal-card"><span class="signal-icon">🚦</span><div class="signal-content"><small>TRAFFIC</small><b>${traffic.available ? esc(traffic.traffic_density).toUpperCase() : 'OFF'}</b><em>${traffic.available ? `${traffic.current_speed_kmh} km/h current` : 'TomTom key required'}</em></div></div>
        <div class="signal-card"><span class="signal-icon">!</span><div class="signal-content"><small>INCIDENTS</small><b>${incidents.available ? incidents.incidents.length : 'OFF'}</b><em>${incidents.available ? 'Live nearby' : 'Provider unavailable'}</em></div></div>
      </div>
      <div class="weather-card"><div class="weather-head"><span class="weather-big">${weatherIcon(weather.weather)}</span><div><b>${weather.available ? esc(weather.weather) : 'Weather unavailable'}</b><small>${weather.available ? `Observed ${esc(weather.observed_at || 'now')}` : 'Try refresh later'}</small></div><span class="weather-status ${weatherStatus.toLowerCase()}">${weatherStatus}</span></div><div class="weather-stats"><div><small>Rain</small><b>${weather.available ? (weather.rain_mm ?? 0)+' mm' : '—'}</b></div><div><small>Wind</small><b>${weather.available ? (weather.wind_kmh ?? 0)+' km/h' : '—'}</b></div><div><small>Visibility</small><b>${weather.available ? ((weather.visibility_m ?? 0)/1000).toFixed(1)+' km' : '—'}</b></div><div><small>Precipitation</small><b>${weather.available ? (weather.precipitation_mm ?? 0)+' mm' : '—'}</b></div></div><div class="source-line">${providerBadge(!!weather.available,'Open-Meteo')} ${providerBadge(!!traffic.available,'TomTom Traffic')} ${providerBadge(!!incidents.available,'TomTom Incidents')}</div></div>
      <div class="intel-section"><span class="eyebrow">EVIDENCE BREAKDOWN</span><div class="metric-list">${evidence || '<p class="muted">No live evidence is currently available.</p>'}</div></div>
      <div class="evidence-grid"><div><small>Historical accidents</small><b>${data.historical.accidents}</b></div><div><small>Nearby reports</small><b>${data.complaints.nearby}</b></div><div><small>Top cause</small><b>${esc(data.historical.top_cause)}</b></div><div><small>Peak hour</small><b>${data.historical.peak_hour === null ? '—' : String(data.historical.peak_hour).padStart(2,'0')+':00'}</b></div></div>
      <div class="explain"><b>ML context</b><p>${data.model?.available ? `The Random Forest evaluated the available time, road, weather and traffic context. Model estimate: <strong>${Math.round(data.model.predicted_risk*100)}/100</strong>.` : 'The ML estimate is unavailable because the required live context could not be assembled.'}</p></div>
      <div class="data-note">Historical records and citizen reports are never labelled as live.</div>`;
  } catch (error) {
    $('#intel').innerHTML = `<div class="error"><b>Area intelligence unavailable</b><p>${esc(error.message)}</p><button class="btn secondary" onclick="selected(${lat},${lng},true)">Try again</button></div>`;
  }
}

async function searchPlace() {
  const query = $('#place').value.trim();
  if (!query) return;
  try {
    const response = await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(query)}`, {headers:{Accept:'application/json'}});
    const results = await response.json();
    if (!results.length) throw new Error('Place not found');
    const lat = Number(results[0].lat), lng = Number(results[0].lon);
    map.setView([lat,lng],13);
    selected(lat,lng);
  } catch (error) { toast(error.message); }
}

function locate() {
  if (!navigator.geolocation) return toast('Browser location is unavailable');
  navigator.geolocation.getCurrentPosition(
    (position) => { map.setView([position.coords.latitude,position.coords.longitude],14); selected(position.coords.latitude,position.coords.longitude); },
    () => toast('Location permission was not granted')
  );
}

function reportPage() {
  shell('Report a civic issue', `
    <section class="page-intro"><span class="eyebrow">REPORT</span><h2>Tell CivicCare what you see.</h2><p>Give a clear description and location. The local intelligence engine will classify the report and estimate its urgency.</p></section>
    <div class="report-layout">
      <div class="panel-card form-panel">
        <div class="form-progress"><span class="active">1</span><div></div><span class="active">2</span><div></div><span>3</span><small>Describe · Locate · Submit</small></div>
        <form id="reportForm" class="report-form">
          <div class="form-section"><span class="eyebrow">01 · DESCRIBE</span><h3>What is happening?</h3><label>Issue title<input class="input" name="title" required placeholder="Deep pothole near junction"></label><label>Description<textarea class="textarea" name="description" required placeholder="Describe what you saw, where it is and why it matters."></textarea></label></div>
          <div class="form-section"><span class="eyebrow">02 · LOCATE</span><h3>Where is it?</h3><div class="form-grid"><label>Address / landmark<input class="input" name="address" placeholder="Optional landmark or street"></label><div class="location-button"><button type="button" class="btn secondary" id="reportLoc">Use my location</button></div><label>Latitude<input class="input" id="rlat" name="latitude" type="number" step="any" placeholder="12.9716"></label><label>Longitude<input class="input" id="rlng" name="longitude" type="number" step="any" placeholder="77.5946"></label></div></div>
          <div class="form-section"><span class="eyebrow">03 · EVIDENCE</span><h3>Optional photo</h3><label class="upload-box"><span>＋</span><b>Add an image</b><small>JPG, PNG or WEBP · max 8 MB</small><input class="input" name="image" type="file" accept="image/*"></label></div>
          <div id="reportOut"></div>
          <button class="primary wide" type="submit">Submit civic report <span>→</span></button>
        </form>
      </div>
      <aside class="panel-card guidance"><span class="eyebrow">GOOD REPORT</span><h3>Make it useful</h3><ul><li>Use a specific title.</li><li>Mention the exact location or landmark.</li><li>Explain the visible problem clearly.</li><li>Add a photo when it helps.</li></ul><div class="privacy-note"><b>Your account</b><p>Your reports are visible to you in My Reports. Live area intelligence is separate from your personal report history.</p></div></aside>
    </div>`);

  $('#reportLoc').onclick = () => navigator.geolocation?.getCurrentPosition(
    (p) => { $('#rlat').value = p.coords.latitude; $('#rlng').value = p.coords.longitude; toast('Location added'); },
    () => toast('Location permission was not granted')
  );
  $('#reportForm').onsubmit = async (event) => {
    event.preventDefault();
    const submit = event.submitter;
    submit.disabled = true;
    try {
      const data = await api('/api/complaints', {method:'POST', body:new FormData(event.target)});
      $('#reportOut').innerHTML = `<div class="success"><b>${esc(data.complaint.public_id)} submitted</b><p>${esc(data.analysis.category)} · ${esc(data.analysis.priority)} · ${Math.round(data.analysis.confidence*100)}% classification confidence.</p><div class="routing-note"><strong>Routed to the responsible authority</strong><span>${esc(data.assigned_authority?.department || data.analysis.department || 'Relevant civic department')}</span><b>${esc(data.assigned_authority?.name || 'Assigned civic authority')}</b><small>Your complaint is now in this authority's queue. Open My Reports to track every action from acknowledgement to resolution.</small></div></div>`;
      event.target.reset();
    } catch (error) {
      $('#reportOut').innerHTML = `<div class="error">${esc(error.message)}</div>`;
    } finally { submit.disabled = false; }
  };
}

async function reportsPage() {
  shell('My reports', `
    <section class="page-intro report-list-intro"><div><span class="eyebrow">YOUR ACTIVITY</span><h2>Reports you submitted</h2><p>Keep track of the issues you have reported through CivicCare.</p></div><button class="primary" id="newReport">＋ New report</button></section>
    <div id="reportsList" class="reports-list"><div class="panel-card loading-state"><h3>Loading your reports…</h3><div class="loading-bar"></div></div></div>
  `);
  $('#newReport').onclick = () => show('report');
  await loadReports();
}

async function loadReports() {
  try {
    const reports = await api('/api/complaints');
    if (!reports.length) {
      $('#reportsList').innerHTML = `<div class="empty-card"><span class="empty-icon">✓</span><h3>No reports yet</h3><p>When you submit a civic issue, it will appear here.</p><button class="primary" id="emptyReport">Create your first report</button></div>`;
      $('#emptyReport').onclick = () => show('report');
      return;
    }
    $('#reportsList').innerHTML = reports.map((item) => `
      <article class="report-card">
        <div class="report-card-main"><div class="report-meta"><span>${esc(item.public_id)}</span><span>•</span><span>${esc(item.category)}</span></div><h3>${esc(item.title)}</h3><p>${esc(item.description)}</p><div class="report-routing-mini"><b>Received by</b><span>${esc(item.department || 'Assigned civic authority')}</span><small>Track authority action and resolution</small></div><div class="report-tags"><span>${esc(item.status)}</span><span>${esc(item.priority)}</span>${item.address ? `<span>${esc(item.address)}</span>` : ''}</div></div>
        <div class="report-card-side"><span class="status-pill ${String(item.status||'').toLowerCase()}">${esc(item.status)}</span><button class="text-btn" data-report-id="${item.id}">View details →</button></div>
      </article>`).join('');
    $$('[data-report-id]').forEach((button) => button.onclick = () => reportDetail(button.dataset.reportId));
  } catch (error) { $('#reportsList').innerHTML = `<div class="error">${esc(error.message)}</div>`; }
}

async function reportDetail(id) {
  try {
    const item = await api(`/api/complaints/${id}`);
    const timeline = (item.actions || []).map((action) => `<div class="timeline-item"><span></span><div><b>${esc(action.action)}</b><small>${esc(action.created_at || '')}</small><p>${esc(action.note || '')}</p></div></div>`).join('');
    const authority = item.assigned_authority;
    const steps = ['SUBMITTED','ASSIGNED','ACKNOWLEDGED','IN_PROGRESS','RESOLVED'];
    const statusIndex = item.status === 'OPEN' ? 0 : item.status === 'ESCALATED' ? 2 : item.status === 'REJECTED' ? 4 : Math.max(0, steps.indexOf(item.status));
    const progress = steps.map((step, i) => `<div class="track-step ${i <= statusIndex ? 'done' : ''}"><span>${i < statusIndex ? '✓' : i + 1}</span><b>${step === 'IN_PROGRESS' ? 'In progress' : step.charAt(0) + step.slice(1).toLowerCase()}</b></div>`).join('');
    $('#content').innerHTML = `<div class="content"><button class="back-btn" id="backReports">← Back to my reports</button><section class="detail-head"><div><span class="eyebrow">${esc(item.public_id)}</span><h2>${esc(item.title)}</h2><p>${esc(item.description)}</p></div><span class="status-pill ${String(item.status||'').toLowerCase()}">${esc(item.status)}</span></section><section class="track-panel"><div class="track-header"><div><span class="eyebrow">LIVE COMPLAINT TRACKING</span><h2>Where your complaint is now</h2></div><strong>${esc(item.public_id)}</strong></div><div class="track-line">${progress}</div></section><div class="detail-grid"><div class="panel-card"><span class="eyebrow">AUTHORITY RECEIVING THIS REPORT</span><div class="authority-receiver"><div class="receiver-icon">🏢</div><div><h3>${esc(authority?.department || item.department || 'Responsible Civic Authority')}</h3><b>${esc(authority?.name || 'Assigned authority officer')}</b><small>${esc(authority?.email || 'Department queue')}</small><p>This department receives the complaint, takes action and records every status update visible to you.</p></div></div><div class="detail-metrics"><div><small>Category</small><b>${esc(item.category)}</b></div><div><small>Priority</small><b>${esc(item.priority)}</b></div><div><small>AI confidence</small><b>${Math.round((item.confidence || 0)*100)}%</b></div><div><small>Location</small><b>${esc(item.address || 'Not provided')}</b></div></div></div><div class="panel-card"><span class="eyebrow">AUTHORITY ACTIVITY</span><div class="timeline">${timeline || '<p class="muted">Waiting for the assigned authority to acknowledge the complaint.</p>'}</div></div></div></div>`;
    $('#backReports').onclick = () => reportsPage();
  } catch (error) { toast(error.message); }
}

function initAuthorityMap(reports) {
  const el = document.getElementById('authorityMap');
  if (!el || typeof L === 'undefined') return;
  if (window.authorityMapInstance) { try { window.authorityMapInstance.remove(); } catch (_) {} }
  const points = (reports || []).filter(r => Number.isFinite(Number(r.latitude)) && Number.isFinite(Number(r.longitude)));
  let center = [12.9716,77.5946];
  if (points.length) {
    center = [points.reduce((a,r)=>a+Number(r.latitude),0)/points.length, points.reduce((a,r)=>a+Number(r.longitude),0)/points.length];
  }
  const m = L.map(el,{zoomControl:true}).setView(center, points.length ? 13 : 11);
  window.authorityMapInstance = m;
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors'}).addTo(m);
  points.forEach(r => {
    const priority = String(r.priority || '').toUpperCase();
    const fill = priority === 'CRITICAL' ? '#A64040' : priority === 'HIGH' ? '#A96E1E' : '#2F6B4F';
    L.circleMarker([Number(r.latitude),Number(r.longitude)],{radius:8,color:'#FFFFFF',weight:2,fillColor:fill,fillOpacity:.95})
      .bindPopup(`<b>${esc(r.public_id || 'Complaint')}</b><br>${esc(r.title || 'Civic report')}<br><strong>${esc(priority || 'NORMAL')}</strong><br><small>${esc(r.status || 'OPEN')} · ${esc(r.address || 'Location provided')}</small>`).addTo(m);
  });
  if (points.length > 1) {
    const bounds = L.latLngBounds(points.map(r => [Number(r.latitude),Number(r.longitude)]));
    m.fitBounds(bounds.pad(.2));
  }
}

async function adminConfigPage() {
  shell('System configuration', `
    <section class="authority-hero"><div><span class="eyebrow">ADMINISTRATION</span><h2>Connect live civic data providers.</h2><p>Only administrators can change provider configuration. The application never displays the full secret after it is saved.</p></div><div class="authority-badge"><span>●</span><b>System</b><small>Configuration</small></div></section>
    <section class="section-block two-col">
      <div class="panel-card"><span class="eyebrow">LIVE TRAFFIC</span><h2>TomTom API</h2><p class="muted">Required for current traffic flow, speed, congestion and traffic incidents.</p><div id="configStatus" class="config-status loading-state">Checking configuration…</div><label>TomTom API key<input id="tomtomKey" class="input" type="password" placeholder="Paste your TomTom API key"></label><button id="saveTomTom" class="primary wide">Save TomTom key</button></div>
      <div class="panel-card"><span class="eyebrow">NO KEY REQUIRED</span><h2>Other providers</h2><div class="provider-list"><div><b>Open-Meteo</b><span>Weather · ready</span></div><div><b>OpenStreetMap / Nominatim</b><span>Geocoding · ready</span></div><div><b>Overpass</b><span>Map infrastructure · ready</span></div><div><b>Local Random Forest</b><span>Historical accident risk · ready</span></div></div></div>
      <div class="panel-card"><span class="eyebrow">LOCAL DATA STORE</span><h2>Application database</h2><p class="muted">Citizen accounts, complaints and authority actions are stored in SQLite. The database path can be changed with <code>CIVICCARE_DB_PATH</code>.</p><div id="databaseStatus" class="config-status loading-state">Checking database…</div></div>
    </section>`);
  async function loadConfig(){ try { const c=await api('/api/admin/config'); if(!c.tomtom_configured){ $('#configStatus').innerHTML='<b class="config-error">Not configured</b><span>Add TOMTOM_API_KEY in .env or paste it below.</span>'; } else { $('#configStatus').innerHTML='<b>Testing TomTom…</b><span>Checking the Traffic Flow API with a live request.</span>'; try { const t=await api('/api/admin/config/tomtom/test'); if(t.connected){ $('#configStatus').innerHTML='<b class="config-ok">Connected ✓</b><span>TomTom Traffic Flow API is responding. Live traffic and incidents are enabled.</span>'; } else { $('#configStatus').innerHTML=`<b class="config-error">Configured, but not connected</b><span>${esc(t.message||'TomTom request failed')}${t.http_status?` · HTTP ${t.http_status}`:''}</span>`; } } catch(e){ $('#configStatus').innerHTML=`<b class="config-error">Connection test failed</b><span>${esc(e.message)}</span>`; } } } catch(e){ $('#configStatus').textContent=e.message; } try { const d=await api('/api/admin/database'); $('#databaseStatus').innerHTML = `<b>${esc(d.mode)}</b><span>${esc(d.path)}</span><span>${d.counts.users} users · ${d.counts.complaints} complaints · ${d.counts.actions} actions · ${d.counts.accident_records} accident records</span>`; } catch(e){ $('#databaseStatus').textContent=e.message; } }
  $('#saveTomTom').onclick=async()=>{ const key=$('#tomtomKey').value.trim(); if(!key) return toast('Paste the TomTom API key first'); const fd=new FormData(); fd.append('api_key',key); const b=$('#saveTomTom'); b.disabled=true; try{ await api('/api/admin/config/tomtom',{method:'POST',body:fd}); $('#tomtomKey').value=''; toast('TomTom key saved'); await loadConfig(); }catch(e){toast(e.message)}finally{b.disabled=false} };
  await loadConfig();
}

async function authorityPage() {
  shell('Authority desk', `
    <section class="authority-hero"><div><span class="eyebrow">RESPONSIBLE CIVIC TEAM</span><h2>Review and resolve assigned reports.</h2><p>Complaints are routed automatically from CivicCare's classification engine. This workspace is only visible to authorized civic staff.</p></div><div class="authority-badge"><span>●</span><b>${esc(user?.department || 'Administration')}</b><small>Assigned queue</small></div></section>
    <div id="authorityStats" class="stat-grid compact-stats"><div class="stat-card loading-card"></div><div class="stat-card loading-card"></div><div class="stat-card loading-card"></div><div class="stat-card loading-card"></div></div>
    <section class="authority-map-panel"><div class="authority-map-header"><div><span class="eyebrow">DEPARTMENT MAP</span><h2>${esc(user?.department || 'Authority')} operational map</h2><p>View assigned complaints, nearby civic reports and available area evidence.</p></div><span class="quiet-badge">Department-filtered view</span></div><div class="authority-map-card"><div id="authorityMap"></div></div></section>
    <section class="section-block"><div class="section-heading"><div><span class="eyebrow">ASSIGNED QUEUE</span><h2>Reports needing attention</h2></div><button class="btn secondary" id="refreshAuthority">Refresh</button></div><div id="authorityQueue" class="authority-queue"><div class="panel-card loading-state"><h3>Loading assigned reports…</h3><div class="loading-bar"></div></div></div></section>
  `);
  $('#refreshAuthority').onclick = loadAuthority;
  await loadAuthority();
}

async function loadAuthority() {
  try {
    const reports = await api('/api/authority/queue');
    const open = reports.filter(r => !['RESOLVED','REJECTED'].includes(r.status)).length;
    const critical = reports.filter(r => r.priority === 'CRITICAL').length;
    const resolved = reports.filter(r => r.status === 'RESOLVED').length;
    const high = reports.filter(r => ['HIGH','CRITICAL'].includes(r.priority) && !['RESOLVED','REJECTED'].includes(r.status)).length;
    $('#authorityStats').innerHTML = `<div class="stat-card"><span>Assigned</span><b>${reports.length}</b><small>Total routed reports</small></div><div class="stat-card"><span>Open</span><b>${open}</b><small>Needs action</small></div><div class="stat-card"><span>High priority</span><b>${high}</b><small>High + critical</small></div><div class="stat-card"><span>Resolved</span><b>${resolved}</b><small>Completed reports</small></div>`;
    initAuthorityMap(reports);
    if (!reports.length) { $('#authorityQueue').innerHTML = `<div class="empty-card"><span class="empty-icon">✓</span><h3>Queue is clear</h3><p>No reports are currently assigned to this civic desk.</p></div>`; return; }
    $('#authorityQueue').innerHTML = reports.map(r => `<article class="authority-card"><div class="authority-card-main"><div class="report-meta"><span>${esc(r.public_id)}</span><span>•</span><span>${esc(r.category)}</span><span>•</span><span>${esc(r.department)}</span></div><h3>${esc(r.title)}</h3><p>${esc(r.description)}</p><div class="authority-received"><b>Citizen:</b> ${esc(r.citizen?.name || 'Citizen')} <span>·</span> <b>Received by:</b> ${esc(r.assigned_authority?.name || user?.name || 'Authority desk')}</div><div class="report-tags"><span class="status-pill ${String(r.status||'').toLowerCase()}">${esc(r.status)}</span><span>${esc(r.priority)}</span><span>${esc(r.address || 'Location not provided')}</span></div></div><div class="authority-actions"><label>Update status<select class="input status-select" data-id="${r.id}"><option value="ACKNOWLEDGED" ${r.status==='ACKNOWLEDGED'?'selected':''}>Acknowledged</option><option value="IN_PROGRESS" ${r.status==='IN_PROGRESS'?'selected':''}>In progress</option><option value="RESOLVED" ${r.status==='RESOLVED'?'selected':''}>Resolved</option><option value="ESCALATED" ${r.status==='ESCALATED'?'selected':''}>Escalated</option><option value="REJECTED" ${r.status==='REJECTED'?'selected':''}>Rejected</option></select></label><textarea class="textarea action-note" data-id="${r.id}" placeholder="Add an update note…"></textarea><button class="primary wide save-action" data-id="${r.id}">Save update</button></div></article>`).join('');
    $$('.save-action').forEach(btn => btn.onclick = async () => {
      const id = btn.dataset.id; const select = document.querySelector(`.status-select[data-id="${id}"]`); const note = document.querySelector(`.action-note[data-id="${id}"]`);
      if (!note.value.trim()) return toast('Add a short update note before saving');
      btn.disabled = true;
      try { const fd = new FormData(); fd.append('status', select.value); fd.append('note', note.value.trim()); await api(`/api/complaints/${id}/action`, {method:'POST', body:fd}); toast('Report updated'); await loadAuthority(); } catch (e) { toast(e.message); } finally { btn.disabled = false; }
    });
  } catch (error) { $('#authorityQueue').innerHTML = `<div class="error">${esc(error.message)}</div>`; }
}


auth();
