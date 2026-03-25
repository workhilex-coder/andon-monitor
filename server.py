"""
ANDON CLOUD API SERVER - PWA s push notifikacemi
Nahraj na PythonAnywhere + GitHub (Railway)

Na PythonAnywhere nainstaluj:
  pip install flask pywebpush
"""

from flask import Flask, request, jsonify, Response
from datetime import datetime, timezone
import os
import json

app = Flask(__name__)

_state = {
    "timestamp":   None,
    "lines":       {},
    "alarm_lines": [],
    "alarm_count": 0,
    "total_lines": 0,
    "received_at": None,
}

# Push notifikace - seznam odberatelu
_subscriptions = []

SECRET = os.environ.get("ANDON_SECRET", "HiLex2024Andon")

# VAPID klice pro push notifikace
VAPID_PUBLIC  = "BEqWsUBfNUvzQFlzD1adPuh-PsEOAyBuoo30ZhWMy6aM45ofRZHLWREzsJSv0zvmQRuEUIFLQVcYvD5sNjt0r_g"
VAPID_PRIVATE = os.environ.get("VAPID_PRIVATE", "LS0tLS1CRUdJTiBFQyBQUklWQVRFIEtFWS0tLS0tCk1IY0NBUUVFSVBsUVA3dmo0TFlWM0pya0hqZlJVMGtyT28wazZVNThtRlpXVFE1cGpsSHpvQW9HQ0NxR1NNNDkKQXdFSG9VUURRZ0FFU3BheFFGODFTL05BV1hNUFZwMCs2SDQrd1E0RElHNmlqZlJtRll6THBvemptaDlGa2N0WgpFVE93bEsvVE8rWkJHNFJRZ1V0QlZ4aThQbXcyTzNTditBPT0KLS0tLS1FTkQgRUMgUFJJVkFURSBLRVktLS0tLQo")
VAPID_EMAIL   = "mailto:admin@hi-lex.cz"

def send_push_notifications(alarm_lines):
    """Posle push notifikace vsem odberatelum."""
    if not _subscriptions:
        return
    try:
        from pywebpush import webpush, WebPushException
        import base64
        
        priv_key_pem = base64.urlsafe_b64decode(VAPID_PRIVATE + "==").decode()
        
        payload = json.dumps({
            "title": f"⚠️ ANDON PORUCHA",
            "body":  f"Porucha na: {', '.join(alarm_lines)}",
            "lines": alarm_lines,
        })
        
        dead = []
        for sub in _subscriptions:
            try:
                webpush(
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=priv_key_pem,
                    vapid_claims={"sub": VAPID_EMAIL}
                )
            except WebPushException as e:
                if "410" in str(e) or "404" in str(e):
                    dead.append(sub)
        
        for sub in dead:
            _subscriptions.remove(sub)
            
    except ImportError:
        pass  # pywebpush neni nainstalovano
    except Exception as e:
        print(f"Push chyba: {e}")

# ─── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/update", methods=["POST"])
def update():
    if request.headers.get("X-Secret") != SECRET:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    
    prev_alarms = set(_state.get("alarm_lines", []))
    _state.update(data)
    _state["received_at"] = datetime.now(timezone.utc).isoformat()
    
    # Posli push notifikace kdyz jsou nove poruchy
    new_alarms = set(_state.get("alarm_lines", []))
    if new_alarms and new_alarms != prev_alarms:
        send_push_notifications(list(new_alarms))
    
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

@app.route("/api/subscribe", methods=["POST"])
def subscribe():
    """Registrace pro push notifikace."""
    sub = request.get_json(force=True, silent=True)
    if not sub:
        return jsonify({"error": "Invalid"}), 400
    if sub not in _subscriptions:
        _subscriptions.append(sub)
    return jsonify({"ok": True, "count": len(_subscriptions)})

@app.route("/api/unsubscribe", methods=["POST"])
def unsubscribe():
    sub = request.get_json(force=True, silent=True)
    if sub in _subscriptions:
        _subscriptions.remove(sub)
    return jsonify({"ok": True})

@app.route("/api/vapid-public")
def vapid_public():
    return jsonify({"key": VAPID_PUBLIC})

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "Andon Monitor",
        "short_name": "Andon",
        "description": "Monitoring poruch na Andon boardu",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1a1a2e",
        "theme_color": "#1a1a2e",
        "orientation": "portrait",
        "icons": [
            {"src": "/icon.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon.png", "sizes": "512x512", "type": "image/png"},
        ]
    })

@app.route("/icon.png")
def icon():
    # Jednoducha SVG ikona prevedena na PNG response
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='192' height='192' viewBox='0 0 192 192'>
      <rect width='192' height='192' rx='32' fill='%231a1a2e'/>
      <text x='96' y='130' font-size='100' text-anchor='middle'>🏭</text>
    </svg>"""
    return Response(svg, mimetype="image/svg+xml",
                   headers={"Content-Disposition": "inline; filename=icon.svg"})

@app.route("/sw.js")
def service_worker():
    sw = """
const CACHE = 'andon-v1';

self.addEventListener('install', e => {
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(clients.claim());
});

// Push notifikace
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data.json(); } catch(err) {}

  const title = data.title || '⚠️ Andon Porucha';
  const body  = data.body  || 'Nová porucha na lince';
  const lines = data.lines || [];

  e.waitUntil(
    self.registration.showNotification(title, {
      body:    body,
      icon:    '/icon.png',
      badge:   '/icon.png',
      tag:     'andon-alarm',
      renotify: true,
      requireInteraction: true,
      vibrate: [300, 100, 300, 100, 300],
      data:    { lines: lines, url: '/' },
      actions: [
        { action: 'open',    title: '👁️ Zobrazit' },
        { action: 'dismiss', title: '✖️ Zavřít'   },
      ]
    })
  );
});

// Klik na notifikaci
self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'dismiss') return;
  e.waitUntil(
    clients.matchAll({ type: 'window' }).then(list => {
      for (const client of list) {
        if (client.url === '/' && 'focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow('/');
    })
  );
});
"""
    return Response(sw, mimetype="application/javascript")

@app.route("/", methods=["GET"])
def index():
    html = """<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta name="mobile-web-app-capable" content="yes"/>
  <meta name="apple-mobile-web-app-capable" content="yes"/>
  <meta name="theme-color" content="#1a1a2e"/>
  <link rel="manifest" href="/manifest.json"/>
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
    .info-bar {
      background: #2c3e50; padding: 8px 12px; border-radius: 8px;
      margin-bottom: 10px; font-size: 12px; color: #aaa;
      display: flex; justify-content: space-between; align-items: center;
    }
    .push-btn {
      background: #27ae60; color: white; border: none;
      padding: 4px 10px; border-radius: 4px; font-size: 12px; cursor: pointer;
    }
    .push-btn.off { background: #7f8c8d; }
    .filter-bar {
      display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px;
    }
    .filter-btn {
      padding: 6px 14px; border-radius: 20px; border: 2px solid #555;
      background: #2c3e50; color: #aaa; font-size: 13px;
      cursor: pointer; transition: all 0.2s; user-select: none;
    }
    .filter-btn.active.asm   { border-color: #3498db; color: #3498db; background: #1a2a3a; }
    .filter-btn.active.cable { border-color: #9b59b6; color: #9b59b6; background: #2a1a3a; }
    .filter-btn.active.fipg  { border-color: #e67e22; color: #e67e22; background: #3a2a1a; }
    .filter-btn.active.mold  { border-color: #2ecc71; color: #2ecc71; background: #1a3a2a; }
    table { border-collapse: collapse; width: 100%; }
    td { padding: 8px 10px; border-bottom: 1px solid #333; font-size: 14px; }
    .alarm-row td { background: #3a1a1a; }
    .ok   { color: #2ecc71; }
    .warn { color: #e74c3c; font-weight: bold; }
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
  <div id="activate" onclick="activateAll()">👆 KLIKNI PRO AKTIVACI ZVUKU A NOTIFIKACÍ</div>
  <div class="info-bar">
    <span id="push-status">🔕 Push notifikace vypnuté</span>
    <button class="push-btn off" id="push-btn" onclick="togglePush()">Zapnout</button>
  </div>
  <div class="filter-bar">
    <span style="font-size:12px;color:#aaa;line-height:32px;">Zobrazit:</span>
    <button class="filter-btn asm active"   onclick="toggleFilter('asm')"   id="btn-asm">🔵 Assembly</button>
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
const LINE_GROUP = {
  'A01':'asm','A02':'asm','A03':'asm','A04':'asm',
  'A05':'asm','A06':'asm','A07':'asm','A08':'asm',
  'C01':'cable','C02':'cable','C03':'cable','C04':'cable',
  'F01':'fipg','F02':'fipg','F03':'fipg',
  'M01':'mold','M02':'mold','M03':'mold',
  'M04':'mold','M05':'mold','M06':'mold',
};

let activeFilters = JSON.parse(localStorage.getItem('andon_filters') || '["asm","cable","fipg","mold"]');
let audioCtx = null, alarmInterval = null, soundReady = false, pendingAlarm = false;
let lastTs = null, lastData = null;
let swReg = null, pushSub = null;

// ── Zvuk ──────────────────────────────────────────────────────────────────────

function activateAll() {
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
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      const dist = audioCtx.createWaveShaper();
      const curve = new Float32Array(256);
      for (let i = 0; i < 256; i++) {
        const x = (i*2)/256 - 1;
        curve[i] = (Math.PI+400)*x / (Math.PI+400*Math.abs(x));
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
  stopAlarm(); playAlarm();
  alarmInterval = setInterval(playAlarm, 2000);
}
function stopAlarm() {
  if (alarmInterval) { clearInterval(alarmInterval); alarmInterval = null; }
}

// ── Service Worker + Push ─────────────────────────────────────────────────────

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

async function initServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  try {
    swReg = await navigator.serviceWorker.register('/sw.js');
    console.log('SW registrovan');
    // Zkontroluj existujici subscription
    pushSub = await swReg.pushManager.getSubscription();
    if (pushSub) updatePushUI(true);
  } catch(e) { console.log('SW chyba:', e); }
}

async function togglePush() {
  if (pushSub) {
    // Odhlasit
    await pushSub.unsubscribe();
    await fetch('/api/unsubscribe', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(pushSub.toJSON())
    });
    pushSub = null;
    updatePushUI(false);
  } else {
    // Prihlasit
    try {
      const permResult = await Notification.requestPermission();
      if (permResult !== 'granted') {
        alert('Musíš povolit notifikace v nastavení prohlížeče!');
        return;
      }
      const vapidRes = await fetch('/api/vapid-public');
      const { key } = await vapidRes.json();
      pushSub = await swReg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key)
      });
      await fetch('/api/subscribe', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(pushSub.toJSON())
      });
      updatePushUI(true);
      alert('✅ Push notifikace zapnuty! Budeš dostávat upozornění i při zavřeném prohlížeči.');
    } catch(e) {
      console.log('Push chyba:', e);
      alert('Chyba při zapínání notifikací: ' + e.message);
    }
  }
}

function updatePushUI(enabled) {
  const btn = document.getElementById('push-btn');
  const status = document.getElementById('push-status');
  if (enabled) {
    btn.textContent = 'Vypnout';
    btn.className = 'push-btn';
    status.textContent = '🔔 Push notifikace zapnuté';
  } else {
    btn.textContent = 'Zapnout';
    btn.className = 'push-btn off';
    status.textContent = '🔕 Push notifikace vypnuté';
  }
}

// ── Filtr ─────────────────────────────────────────────────────────────────────

function toggleFilter(group) {
  const idx = activeFilters.indexOf(group);
  if (idx >= 0) {
    if (activeFilters.length === 1) return;
    activeFilters.splice(idx, 1);
  } else {
    activeFilters.push(group);
  }
  localStorage.setItem('andon_filters', JSON.stringify(activeFilters));
  updateFilterButtons();
  renderData(lastData);
}

function updateFilterButtons() {
  ['asm','cable','fipg','mold'].forEach(g => {
    const btn = document.getElementById('btn-' + g);
    btn.classList.toggle('active', activeFilters.includes(g));
  });
}

// ── Data ──────────────────────────────────────────────────────────────────────

function renderData(data) {
  if (!data) return;
  lastData = data;
  const ts     = (data.timestamp || '').replace('T',' ').substring(0,19);
  const alarms = data.alarm_lines || [];
  const lines  = data.lines || {};

  document.getElementById('ts').textContent = 'Update: ' + ts;

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
    stopAlarm(); pendingAlarm = false;
  }
  lastTs = ts;

  let rows = '';
  Object.keys(lines).sort().forEach(ln => {
    if (!activeFilters.includes(LINE_GROUP[ln])) return;
    const alarm   = lines[ln].alarm;
    const sensors = lines[ln].alarm_sensors || [];
    let detail = '';
    sensors.forEach(s => {
      const isTL  = (s.type==='teamleader') || (s.sensor_id||'').includes('.teamleader@');
      const typ   = isTL ? '<span class="tl">🟡 TL</span>' : '<span class="comp">🔴 H</span>';
      const stroj = (s.sensor_id||'').split('@')[1]?.split('.')[0]?.toUpperCase()||'';
      detail += ' <small>' + typ + ' ' + stroj + '</small>';
    });
    rows += '<tr class="'+(alarm?'alarm-row':'')+'">'+
      '<td>'+(alarm?'🔴':'✅')+'</td>'+
      '<td><b>'+ln+'</b>'+detail+'</td>'+
      '<td class="'+(alarm?'warn':'ok')+'">'+(alarm?'PORUCHA':'OK')+'</td>'+
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

// ── Init ──────────────────────────────────────────────────────────────────────

updateFilterButtons();
initServiceWorker();
load();
setInterval(load, 2000);
</script>
</body>
</html>"""
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
