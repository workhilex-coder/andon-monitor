"""
ANDON CLOUD API SERVER - s real-time refreshem
Nasadit na Railway.app
"""

from flask import Flask, request, jsonify, Response
from datetime import datetime, timezone
import os
import json
import time

app = Flask(__name__)

_state = {
    "timestamp":   None,
    "lines":       {},
    "alarm_lines": [],
    "alarm_count": 0,
    "total_lines": 0,
}

SECRET = os.environ.get("ANDON_SECRET", "HiLex2024Andon")

# ─── API ENDPOINTS ────────────────────────────────────────────────────────────

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

# ─── SERVER-SENT EVENTS (real-time push) ──────────────────────────────────────

@app.route("/api/stream")
def stream():
    """SSE endpoint - posila aktualizace okamzite bez pollingu."""
    def event_stream():
        last_ts = None
        while True:
            current_ts = _state.get("received_at")
            if current_ts != last_ts:
                last_ts = current_ts
                data = json.dumps({
                    "alarm_count": _state["alarm_count"],
                    "alarm_lines": _state["alarm_lines"],
                    "timestamp":   _state["timestamp"],
                })
                yield f"data: {data}\n\n"
            else:
                # Keepalive
                yield f": keepalive\n\n"
            time.sleep(0.5)

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ─── HTML DASHBOARD ───────────────────────────────────────────────────────────

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
    .status-ok   { color: #2ecc71; font-size: 11px; }
    .status-err  { color: #e74c3c; font-size: 11px; }
    .banner {
      background: #e74c3c; color: white; padding: 12px;
      border-radius: 8px; margin-bottom: 12px;
      font-size: 20px; font-weight: bold; text-align: center;
      animation: pulse 1s infinite;
    }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.7} }
    table { border-collapse: collapse; width: 100%; }
    td { padding: 7px 10px; border-bottom: 1px solid #333; font-size: 14px; }
    tr:hover td { background: #2a2a4e; }
    .alarm-row td { background: #3a1a1a; }
    .ok   { color: #2ecc71; }
    .warn { color: #e74c3c; font-weight: bold; }
    #conn { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #aaa; margin-right: 4px; }
    #conn.live { background: #2ecc71; }
  </style>
</head>
<body>
  <h1>🏭 Andon Monitor</h1>
  <div class="ts">
    <span id="conn"></span>
    <span id="ts">Načítám...</span>
  </div>
  <div id="banner" style="display:none"></div>
  <table>
    <thead><tr><th></th><th>Linka</th><th>Stav</th></tr></thead>
    <tbody id="tbody"></tbody>
  </table>

<script>
const conn = document.getElementById('conn');
const tsEl = document.getElementById('ts');
const banner = document.getElementById('banner');
const tbody = document.getElementById('tbody');

function loadFull() {
  fetch('/api/status')
    .then(r => r.json())
    .then(data => {
      const alarms = data.alarm_lines || [];
      const lines  = data.lines || {};
      const ts     = data.timestamp || '';

      tsEl.textContent = 'Update: ' + ts.replace('T',' ').substring(0,19);

      if (alarms.length > 0) {
        banner.style.display = 'block';
        banner.textContent = '⚠️ PORUCHA: ' + alarms.join(', ');
      } else {
        banner.style.display = 'none';
      }

      let rows = '';
      Object.keys(lines).sort().forEach(ln => {
        const info  = lines[ln];
        const alarm = info.alarm;
        const icon  = alarm ? '🔴' : '✅';
        const cls   = alarm ? 'warn' : 'ok';
        const txt   = alarm ? 'PORUCHA' : 'OK';
        rows += `<tr class="${alarm ? 'alarm-row' : ''}">
          <td>${icon}</td>
          <td><b>${ln}</b></td>
          <td class="${cls}">${txt}</td>
        </tr>`;
      });
      tbody.innerHTML = rows;
    })
    .catch(e => console.log(e));
}

// Server-Sent Events pro okamzite aktualizace
function connectSSE() {
  const es = new EventSource('/api/stream');

  es.onopen = () => {
    conn.className = 'live';
    tsEl.textContent = 'Připojeno – čekám na data...';
  };

  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    const alarms = data.alarm_lines || [];
    tsEl.textContent = 'Update: ' + (data.timestamp || '').replace('T',' ').substring(0,19);
    if (alarms.length > 0) {
      banner.style.display = 'block';
      banner.textContent = '⚠️ PORUCHA: ' + alarms.join(', ');
    } else {
      banner.style.display = 'none';
    }
    loadFull();
  };

  es.onerror = () => {
    conn.className = '';
    // Fallback na polling kdyz SSE nefunguje
    setTimeout(connectSSE, 3000);
  };
}

// Spust SSE + nacti data hned
connectSSE();
loadFull();

// Fallback polling kazdych 5s (pro pripad ze SSE nefunguje)
setInterval(loadFull, 5000);
</script>
</body>
</html>"""
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
