"""
ANDON CLOUD API SERVER - s filtrem skupin linek
"""

from flask import Flask, request, jsonify
from datetime import datetime, timezone
import os

app = Flask(__name__)

_state = {
    "timestamp":   None,
    "lines":       {},
    "alarm_lines": [],
    "alarm_count": 0,
    "total_lines": 0,
    "received_at": None,
}

SECRET = os.environ.get("ANDON_SECRET", "HiLex2024Andon")

@app.route("/api/update", methods=["POST"])
def update():
    if request.headers.get("X-Secret") != SECRET:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    _state.update(data)
    _state["received_at"] = datetime.now(timezone.utc).isoformat()
    return jsonify({"ok": True})

@app.route("/api/status", methods=["GET"])
def status():
    return jsonify(_state)

@app.route("/api/alarms", methods=["GET"])
def alarms():
    if not _state["timestamp"]:
        return jsonify({"error": "Zadna data"}), 503
    alarm_detail = []
    for line_name in _state.get("alarm_lines", []):
        line_info = _state["lines"].get(line_name, {})
        alarm_detail.append({
            "line":          line_name,
            "alarm_sensors": line_info.get("alarm_sensors", []),
        })
    return jsonify({
        "timestamp":   _state["timestamp"],
        "alarm_count": _state["alarm_count"],
        "total_lines": _state["total_lines"],
        "alarms":      alarm_detail,
    })

@app.route("/", methods=["GET"])
def index():
    html = """<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta name="mobile-web-app-capable" content="yes"/>
  <meta name="apple-mobile-web-app-capable" content="yes"/>
  <title>Andon Monitor</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: sans-serif; background: #1a1a2e; color: #eee; padding: 12px; }
    h1 { font-size: 20px; margin-bottom: 8px; }
    .ts { font-size: 11px; color: #aaa; margin-bottom: 10px; }
    .banner {
      background: #e74c3c; color: white; padding: 14px;
      border-radius: 8px; margin-bottom: 12px;
      font-size: 20px; font-weight: bold; text-align: center;
      animation: pulse 0.6s infinite;
    }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
    .ok-banner {
      background: #27ae60; color: white; padding: 8px;
      border-radius: 8px; margin-bottom: 12px;
      font-size: 14px; text-align: center;
    }
    /* Filter tlacitka */
    .filter-bar {
      display: flex; flex-wrap: wrap; gap: 6px;
      margin-bottom: 12px;
    }
    .filter-btn {
      padding: 6px 14px; border-radius: 20px; border: 2px solid #555;
      background: #2c3e50; color: #aaa; font-size: 13px;
      cursor: pointer; transition: all 0.2s; user-select: none;
    }
    .filter-btn.active {
      border-color: currentColor; color: white;
      background: #1a1a2e;
    }
    .filter-btn.active.asm  { border-color: #3498db; color: #3498db; background: #1a2a3a; }
    .filter-btn.active.cable { border-color: #9b59b6; color: #9b59b6; background: #2a1a3a; }
    .filter-btn.active.fipg  { border-color: #e67e22; color: #e67e22; background: #3a2a1a; }
    .filter-btn.active.mold  { border-color: #2ecc71; color: #2ecc71; background: #1a3a2a; }
    table { border-collapse: collapse; width: 100%; }
    td { padding: 8px 10px; border-bottom: 1px solid #333; font-size: 14px; }
    .alarm-row td { background: #3a1a1a; }
    .ok   { color: #2ecc71; }
    .warn { color: #e74c3c; font-weight: bold; }
    .hidden { display: none; }
    #dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#e74c3c; margin-right:4px; vertical-align:middle; }
    #dot.live { background:#2ecc71; }
    .tl   { color: #f1c40f; font-weight: bold; }
    .comp { color: #e74c3c; font-weight: bold; }
    small { font-size: 11px; margin-left: 4px; }
    #activate {
      background: #e67e22; color: white; padding: 14px;
      border-radius: 8px; margin-bottom: 12px;
      font-size: 16px; font-weight: bold; text-align: center;
      cursor: pointer; animation: pulse 1s infinite;
    }
  </style>
</head>
<body>
  <h1>🏭 Andon Monitor</h1>
  <div class="ts"><span id="dot"></span><span id="ts">Načítám...</span></div>

  <!-- Aktivace zvuku -->
  <div id="activate" onclick="activateSound()">👆 KLIKNI PRO AKTIVACI ZVUKU</div>

  <!-- Filter skupin -->
  <div class="filter-bar">
    <span style="font-size:12px;color:#aaa;line-height:32px;">Zobrazit:</span>
    <button class="filter-btn asm active"  onclick="toggleFilter('asm')"  id="btn-asm">🔵 Assembly</button>
    <button class="filter-btn cable active" onclick="toggleFilter('cable')" id="btn-cable">🟣 Cable</button>
    <button class="filter-btn fipg active"  onclick="toggleFilter('fipg')"  id="btn-fipg">🟠 FIPG</button>
    <button class="filter-btn mold active"  onclick="toggleFilter('mold')"  id="btn-mold">🟢 Molding</button>
  </div>

  <div id="banner"></div>
  <table>
    <thead><tr><th></th><th>Linka</th><th>Stav</th></tr></thead>
    <tbody id="tbody"></tbody>
  </table>

<script>
// Mapovani linka -> skupina
const LINE_GROUP = {
  'A01':'asm','A02':'asm','A03':'asm','A04':'asm',
  'A05':'asm','A06':'asm','A07':'asm','A08':'asm',
  'C01':'cable','C02':'cable','C03':'cable','C04':'cable',
  'F01':'fipg','F02':'fipg','F03':'fipg',
  'M01':'mold','M02':'mold','M03':'mold',
  'M04':'mold','M05':'mold','M06':'mold',
};

// Aktivni filtry - uloz do localStorage
let activeFilters = JSON.parse(localStorage.getItem('andon_filters') || '["asm","cable","fipg","mold"]');

function saveFilters() {
  localStorage.setItem('andon_filters', JSON.stringify(activeFilters));
}

function toggleFilter(group) {
  const idx = activeFilters.indexOf(group);
  if (idx >= 0) {
    if (activeFilters.length === 1) return; // aspon jedna skupina musi byt
    activeFilters.splice(idx, 1);
  } else {
    activeFilters.push(group);
  }
  saveFilters();
  updateFilterButtons();
  renderData(lastData);
}

function updateFilterButtons() {
  ['asm','cable','fipg','mold'].forEach(g => {
    const btn = document.getElementById('btn-' + g);
    if (activeFilters.includes(g)) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
}

// Zvuk
let audioCtx = null;
let alarmInterval = null;
let soundReady = false;
let pendingAlarm = false;
let lastTs = null;
let lastData = null;

function activateSound() {
  document.getElementById('activate').style.display = 'none';
  try {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    audioCtx.resume().then(() => {
      soundReady = true;
      if (pendingAlarm) { startAlarm(); pendingAlarm = false; }
    });
  } catch(e) {}
}

function playAlarm() {
  if (!soundReady || !audioCtx) return;
  try {
    [0, 0.25, 0.5].forEach(delay => {
      const osc  = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      const dist = audioCtx.createWaveShaper();
      const curve = new Float32Array(256);
      for (let i = 0; i < 256; i++) {
        const x = (i * 2) / 256 - 1;
        curve[i] = (Math.PI + 400) * x / (Math.PI + 400 * Math.abs(x));
      }
      dist.curve = curve;
      osc.connect(dist); dist.connect(gain); gain.connect(audioCtx.destination);
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(960, audioCtx.currentTime + delay);
      osc.frequency.setValueAtTime(720, audioCtx.currentTime + delay + 0.1);
      gain.gain.setValueAtTime(0, audioCtx.currentTime + delay);
      gain.gain.linearRampToValueAtTime(1.0, audioCtx.currentTime + delay + 0.02);
      gain.gain.setValueAtTime(1.0, audioCtx.currentTime + delay + 0.15);
      gain.gain.linearRampToValueAtTime(0, audioCtx.currentTime + delay + 0.22);
      osc.start(audioCtx.currentTime + delay);
      osc.stop(audioCtx.currentTime + delay + 0.25);
    });
  } catch(e) {}
}

function startAlarm() {
  stopAlarm();
  playAlarm();
  alarmInterval = setInterval(playAlarm, 2000);
}

function stopAlarm() {
  if (alarmInterval) { clearInterval(alarmInterval); alarmInterval = null; }
}

function renderData(data) {
  if (!data) return;
  lastData = data;

  const ts     = (data.timestamp || '').replace('T',' ').substring(0,19);
  const alarms = data.alarm_lines || [];
  const lines  = data.lines || {};

  document.getElementById('ts').textContent = 'Update: ' + ts;

  // Filtruj alarmy podle aktivnich skupin
  const filteredAlarms = alarms.filter(ln => activeFilters.includes(LINE_GROUP[ln]));

  const b = document.getElementById('banner');
  if (filteredAlarms.length > 0) {
    b.innerHTML = '<div class="banner">⚠️ PORUCHA: ' + filteredAlarms.join(', ') + '</div>';
    if (ts !== lastTs) {
      if (soundReady) { stopAlarm(); startAlarm(); }
      else pendingAlarm = true;
    }
  } else {
    b.innerHTML = data.timestamp ? '<div class="ok-banner">✅ Sledované linky OK</div>' : '';
    stopAlarm();
    pendingAlarm = false;
  }
  lastTs = ts;

  // Vykresli tabulku - jen aktivni skupiny
  let rows = '';
  Object.keys(lines).sort().forEach(ln => {
    const group = LINE_GROUP[ln] || 'asm';
    if (!activeFilters.includes(group)) return; // skryj neaktivni skupiny

    const alarm   = lines[ln].alarm;
    const sensors = lines[ln].alarm_sensors || [];
    let detail = '';
    if (alarm && sensors.length > 0) {
      sensors.forEach(s => {
        const isTL  = (s.type === 'teamleader') || (s.sensor_id || '').includes('.teamleader@');
        const typ   = isTL ? '<span class="tl">🟡 TL</span>' : '<span class="comp">🔴 H</span>';
        const stroj = (s.sensor_id || '').split('@')[1]?.split('.')[0]?.toUpperCase() || '';
        detail += ' <small>' + typ + ' ' + stroj + '</small>';
      });
    }
    rows += '<tr class="' + (alarm ? 'alarm-row' : '') + '">' +
      '<td>' + (alarm ? '🔴' : '✅') + '</td>' +
      '<td><b>' + ln + '</b>' + detail + '</td>' +
      '<td class="' + (alarm ? 'warn' : 'ok') + '">' + (alarm ? 'PORUCHA' : 'OK') + '</td>' +
      '</tr>';
  });
  document.getElementById('tbody').innerHTML = rows || '<tr><td colspan="3" style="text-align:center;color:#aaa;padding:20px">Vyberte skupiny nahoře</td></tr>';
}

function load() {
  fetch('/api/status')
    .then(r => r.json())
    .then(data => {
      document.getElementById('dot').className = 'live';
      renderData(data);
    })
    .catch(() => { document.getElementById('dot').className = ''; });
}

// Inicializace
updateFilterButtons();
load();
setInterval(load, 2000);
</script>
</body>
</html>"""
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
