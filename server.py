"""
ANDON CLOUD API SERVER - hlasity alarm + opravene barvy
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
    h1 { font-size: 20px; margin-bottom: 4px; }
    .ts { font-size: 11px; color: #aaa; margin-bottom: 12px; }
    .banner {
      background: #e74c3c; color: white; padding: 14px;
      border-radius: 8px; margin-bottom: 12px;
      font-size: 22px; font-weight: bold; text-align: center;
      animation: pulse 0.6s infinite;
    }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
    .ok-banner {
      background: #27ae60; color: white; padding: 8px;
      border-radius: 8px; margin-bottom: 12px;
      font-size: 14px; text-align: center;
    }
    table { border-collapse: collapse; width: 100%; }
    td { padding: 8px 10px; border-bottom: 1px solid #333; font-size: 14px; }
    .alarm-row td { background: #3a1a1a; }
    .ok   { color: #2ecc71; }
    .warn { color: #e74c3c; font-weight: bold; }
    #dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#e74c3c; margin-right:4px; vertical-align:middle; }
    #dot.live { background:#2ecc71; }
    .sound-btn {
      float: right; background: #2c3e50; border: 1px solid #555;
      color: #eee; padding: 4px 10px; border-radius: 4px;
      font-size: 12px; cursor: pointer;
    }
    .sound-btn.muted { opacity: 0.5; }
    .tl  { color: #f1c40f; font-weight: bold; }
    .comp { color: #e74c3c; font-weight: bold; }
    small { font-size: 11px; margin-left: 4px; }
  </style>
</head>
<body>
  <h1>🏭 Andon Monitor <button class="sound-btn" id="soundBtn" onclick="toggleSound()">🔔 Zvuk ZAP</button></h1>
  <div class="ts"><span id="dot"></span><span id="ts">Načítám...</span></div>
  <div id="banner"></div>
  <table>
    <thead><tr><th></th><th>Linka</th><th>Stav</th></tr></thead>
    <tbody id="tbody"></tbody>
  </table>

<script>
let lastAlarmCount = 0;
let lastTs = null;
let soundEnabled = true;
let audioCtx = null;
let alarmInterval = null;

function toggleSound() {
  soundEnabled = !soundEnabled;
  const btn = document.getElementById('soundBtn');
  btn.textContent = soundEnabled ? '🔔 Zvuk ZAP' : '🔕 Zvuk VYP';
  btn.className = soundEnabled ? 'sound-btn' : 'sound-btn muted';
  if (!soundEnabled) stopAlarm();
}

function getCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx;
}

function playAlarm() {
  if (!soundEnabled) return;
  try {
    const ctx = getCtx();
    // Tri ostra pipnuti za sebou - plna hlasitost
    [0, 0.25, 0.5].forEach(delay => {
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      // Distortion pro ostrejsi zvuk
      const dist = ctx.createWaveShaper();
      const curve = new Float32Array(256);
      for (let i = 0; i < 256; i++) {
        const x = (i * 2) / 256 - 1;
        curve[i] = (Math.PI + 400) * x / (Math.PI + 400 * Math.abs(x));
      }
      dist.curve = curve;

      osc.connect(dist);
      dist.connect(gain);
      gain.connect(ctx.destination);

      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(960, ctx.currentTime + delay);
      osc.frequency.setValueAtTime(720, ctx.currentTime + delay + 0.1);

      gain.gain.setValueAtTime(0, ctx.currentTime + delay);
      gain.gain.linearRampToValueAtTime(1.0, ctx.currentTime + delay + 0.02);
      gain.gain.setValueAtTime(1.0, ctx.currentTime + delay + 0.15);
      gain.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.22);

      osc.start(ctx.currentTime + delay);
      osc.stop(ctx.currentTime + delay + 0.25);
    });
  } catch(e) { console.log(e); }
}

function startAlarm() {
  if (!soundEnabled) return;
  if (alarmInterval) return;
  playAlarm();
  alarmInterval = setInterval(playAlarm, 2000);
}

function stopAlarm() {
  if (alarmInterval) {
    clearInterval(alarmInterval);
    alarmInterval = null;
  }
}

function load() {
  fetch('/api/status')
    .then(r => r.json())
    .then(data => {
      document.getElementById('dot').className = 'live';
      const ts     = (data.timestamp || '').replace('T',' ').substring(0,19);
      const alarms = data.alarm_lines || [];
      const lines  = data.lines || {};
      const count  = data.alarm_count || 0;

      document.getElementById('ts').textContent = 'Update: ' + ts;

      const b = document.getElementById('banner');
      if (alarms.length > 0) {
        b.innerHTML = '<div class="banner">⚠️ PORUCHA: ' + alarms.join(', ') + '</div>';
        if (count > lastAlarmCount || ts !== lastTs) {
          startAlarm();
        }
      } else {
        b.innerHTML = data.timestamp ? '<div class="ok-banner">✅ Všechny linky OK</div>' : '';
        stopAlarm();
      }

      lastAlarmCount = count;
      lastTs = ts;

      let rows = '';
      Object.keys(lines).sort().forEach(ln => {
        const alarm   = lines[ln].alarm;
        const sensors = lines[ln].alarm_sensors || [];
        let detail = '';
        if (alarm && sensors.length > 0) {
          sensors.forEach(s => {
            // comp = cervena porucha, teamleader = zluta zadost
            const isComp = (s.type === 'comp') || (s.sensor_id || '').includes('.comp@');
            const typ    = isComp ? '<span class="comp">🔴 H</span>' : '<span class="tl">🟡 TL</span>';
            const stroj  = (s.sensor_id || '').split('@')[1]?.split('.')[0]?.toUpperCase() || '';
            detail += ' <small>' + typ + ' ' + stroj + '</small>';
          });
        }
        rows += '<tr class="' + (alarm ? 'alarm-row' : '') + '">' +
          '<td>' + (alarm ? '🔴' : '✅') + '</td>' +
          '<td><b>' + ln + '</b>' + detail + '</td>' +
          '<td class="' + (alarm ? 'warn' : 'ok') + '">' + (alarm ? 'PORUCHA' : 'OK') + '</td>' +
          '</tr>';
      });
      document.getElementById('tbody').innerHTML = rows;
    })
    .catch(() => {
      document.getElementById('dot').className = '';
    });
}

document.addEventListener('click', () => {
  try { getCtx().resume(); } catch(e) {}
}, { once: true });

load();
setInterval(load, 2000);
</script>
</body>
</html>"""
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
