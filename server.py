"""
ANDON CLOUD API SERVER
Nasadí se na Render.com (free tier).
Přijímá data od Python scraperu a servíruje je mobilním zařízením.
"""

from flask import Flask, request, jsonify
from datetime import datetime, timezone
import os
import json

app = Flask(__name__)

# Sdílený stav (v paměti – pro free tier stačí)
_state = {
    "timestamp":   None,
    "lines":       {},
    "alarm_lines": [],
    "alarm_count": 0,
    "total_lines": 0,
}

SECRET = os.environ.get("ANDON_SECRET", "ZMEN_TOTO_NA_NEJAKY_TAJNY_KLIC")


# ─── ENDPOINTS ────────────────────────────────────────────────────────────────

@app.route("/api/update", methods=["POST"])
def update():
    """Příjem dat od scraperu – chráněno tajným klíčem."""
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
    """Vrátí aktuální stav všech linek – pro mobil/widget."""
    return jsonify(_state)


@app.route("/api/alarms", methods=["GET"])
def alarms():
    """Vrátí pouze poruchové linky – lehčí endpoint pro widget."""
    if not _state["timestamp"]:
        return jsonify({"error": "Žádná data zatím nepřijata"}), 503

    # Sestavíme přehled poruch
    alarm_detail = []
    for line_name in _state.get("alarm_lines", []):
        line_info = _state["lines"].get(line_name, {})
        alarm_detail.append({
            "line":          line_name,
            "alarm_sensors": line_info.get("alarm_sensors", []),
        })

    return jsonify({
        "timestamp":    _state["timestamp"],
        "received_at":  _state.get("received_at"),
        "alarm_count":  _state["alarm_count"],
        "total_lines":  _state["total_lines"],
        "alarms":       alarm_detail,
    })


@app.route("/", methods=["GET"])
def index():
    """Jednoduchá HTML stránka – lze otevřít v prohlížeči nebo v mobilu."""
    alarms = _state.get("alarm_lines", [])
    ts     = _state.get("timestamp", "–")
    lines  = _state.get("lines", {})

    rows = ""
    for line, info in sorted(lines.items()):
        alarm  = info.get("alarm", False)
        color  = "#e74c3c" if alarm else "#2ecc71"
        icon   = "⚠️" if alarm else "✅"
        rows  += f'<tr><td>{icon}</td><td><b>{line}</b></td><td style="color:{color}">{"PORUCHA" if alarm else "OK"}</td></tr>'

    alarm_banner = ""
    if alarms:
        alarm_banner = f'<div style="background:#e74c3c;color:white;padding:12px;border-radius:8px;margin-bottom:16px;font-size:18px;"><b>⚠️ PORUCHA:</b> {", ".join(alarms)}</div>'

    html = f"""<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta http-equiv="refresh" content="30"/>
  <title>Andon Monitor</title>
  <style>
    body {{ font-family: sans-serif; padding: 16px; background: #1a1a2e; color: #eee; }}
    h1   {{ font-size: 22px; margin-bottom: 4px; }}
    .ts  {{ font-size: 12px; color: #aaa; margin-bottom: 16px; }}
    table{{ border-collapse: collapse; width: 100%; }}
    td   {{ padding: 8px 12px; border-bottom: 1px solid #333; }}
    tr:hover td {{ background: #2a2a4e; }}
  </style>
</head>
<body>
  <h1>🏭 Andon Monitor</h1>
  <div class="ts">Poslední update: {ts} &nbsp;·&nbsp; Auto-refresh 30s</div>
  {alarm_banner}
  <table>
    <thead><tr><th></th><th>Linka</th><th>Stav</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>"""
    return html


# ─── SPUŠTĚNÍ ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
