from flask import Flask, request, jsonify, make_response
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import traceback
from typing import Dict, Any, List

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
SUBSCRIPTIONS_FILE = BASE_DIR / "subscriptions.json"

SECRET = os.environ.get("ANDON_SECRET", "HiLex2024Andon")

# Muzes nechat natvrdo, nebo prepsat pres environment promennou.
VAPID_PUBLIC_KEY = os.environ.get(
    "VAPID_PUBLIC_KEY",
    "BMr8IRv5hl9IjnpCXI3yOaz3sBDeK8oK8R-kWmhKKVVbbpzFCHEFSgV22gaJ8BXNxwVNvgGe0Zh0oiCFnJNkr8M",
)
VAPID_PRIVATE_KEY = os.environ.get(
    "VAPID_PRIVATE_KEY",
    "7qW4vUCphoC1rMp3wLh8y1wPeoCHsOf95ksTqxeQuos",
)
VAPID_CLAIMS_SUB = os.environ.get("VAPID_CLAIMS_SUB", "mailto:admin@example.com")

# Podle tveho popisu mas H/TL prohozene uz ve zdroji dat.
# True = prohodit teamleader <-> comp pri zobrazeni i pushi.
REVERSE_SENSOR_MAPPING = True

try:
    from pywebpush import webpush, WebPushException  # type: ignore
    PUSH_AVAILABLE = True
    PUSH_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover
    PUSH_AVAILABLE = False
    PUSH_IMPORT_ERROR = str(exc)

DEFAULT_STATE: Dict[str, Any] = {
    "timestamp": None,
    "lines": {},
    "alarm_lines": [],
    "alarm_count": 0,
    "total_lines": 0,
    "received_at": None,
}

_state: Dict[str, Any] = dict(DEFAULT_STATE)
_last_alarm_snapshot: Dict[str, Dict[str, Any]] = {}

GROUPS = {
    "assembly": "Assembly",
    "cable": "Cable",
    "fipg": "FIPG",
    "molding": "Molding",
}


def log_exception(prefix: str) -> None:
    app.logger.error("%s\n%s", prefix, traceback.format_exc())


def load_json(path: Path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        log_exception(f"Nepodarilo se nacist {path.name}")
    return default


def save_json(path: Path, data) -> None:
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    except Exception:
        log_exception(f"Nepodarilo se ulozit {path.name}")


def load_state() -> None:
    global _state
    data = load_json(STATE_FILE, None)
    if isinstance(data, dict):
        merged = dict(DEFAULT_STATE)
        merged.update(data)
        if not isinstance(merged.get("lines"), dict):
            merged["lines"] = {}
        if not isinstance(merged.get("alarm_lines"), list):
            merged["alarm_lines"] = []
        _state = merged



def save_state() -> None:
    save_json(STATE_FILE, _state)



def load_subscriptions() -> List[Dict[str, Any]]:
    subs = load_json(SUBSCRIPTIONS_FILE, [])
    return subs if isinstance(subs, list) else []



def save_subscriptions(subs: List[Dict[str, Any]]) -> None:
    save_json(SUBSCRIPTIONS_FILE, subs)



def infer_group(line_name: str) -> str:
    if not line_name:
        return "assembly"
    prefix = str(line_name)[0].upper()
    if prefix == "A":
        return "assembly"
    if prefix == "C":
        return "cable"
    if prefix == "F":
        return "fipg"
    if prefix == "M":
        return "molding"
    return "assembly"



def normalize_sensor_type(sensor: Dict[str, Any]) -> str:
    raw_type = (sensor.get("type") or "").strip().lower()
    raw_id = (sensor.get("sensor_id") or "").strip().lower()

    guessed = raw_type
    if not guessed:
        guessed = "teamleader" if "teamleader" in raw_id else "comp"

    if REVERSE_SENSOR_MAPPING:
        if guessed == "teamleader":
            guessed = "comp"
        elif guessed == "comp":
            guessed = "teamleader"

    return guessed



def sensor_label(sensor: Dict[str, Any]) -> str:
    return "TL" if normalize_sensor_type(sensor) == "teamleader" else "H"



def sanitize_sensor(sensor: Any) -> Dict[str, Any]:
    sensor = sensor if isinstance(sensor, dict) else {}
    out = dict(sensor)
    out["type"] = normalize_sensor_type(out)
    out["label"] = sensor_label(out)
    return out



def sanitize_line_info(line_info: Any) -> Dict[str, Any]:
    line_info = line_info if isinstance(line_info, dict) else {}
    sensors = line_info.get("alarm_sensors") or []
    if not isinstance(sensors, list):
        sensors = []
    cleaned_sensors = [sanitize_sensor(s) for s in sensors if isinstance(s, dict)]
    return {
        "alarm": bool(line_info.get("alarm")),
        "alarm_sensors": cleaned_sensors,
    }



def public_state() -> Dict[str, Any]:
    lines: Dict[str, Any] = {}
    for line_name, line_info in (_state.get("lines") or {}).items():
        clean = sanitize_line_info(line_info)
        group = infer_group(str(line_name))
        lines[str(line_name)] = {
            "alarm": clean["alarm"],
            "group": group,
            "group_label": GROUPS.get(group, group.title()),
            "alarm_sensors": clean["alarm_sensors"],
        }

    alarm_lines = [ln for ln in (_state.get("alarm_lines") or []) if isinstance(ln, str)]

    payload = {
        "timestamp": _state.get("timestamp"),
        "received_at": _state.get("received_at"),
        "alarm_count": int(_state.get("alarm_count") or 0),
        "total_lines": int(_state.get("total_lines") or 0),
        "alarm_lines": alarm_lines,
        "groups": GROUPS,
        "lines": dict(sorted(lines.items(), key=lambda kv: kv[0])),
    }
    return payload



def build_alarm_snapshot(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    for line_name, line_info in (state.get("lines") or {}).items():
        clean = sanitize_line_info(line_info)
        active = [s for s in clean["alarm_sensors"] if float(s.get("value", 0) or 0) == 1.0]
        if active:
            group = infer_group(str(line_name))
            snapshot[str(line_name)] = {
                "line": str(line_name),
                "group": group,
                "group_label": GROUPS.get(group, group.title()),
                "sensors": active,
            }
    return snapshot



def diff_new_alarms(old_snapshot: Dict[str, Dict[str, Any]], new_snapshot: Dict[str, Dict[str, Any]]):
    newly_active = []
    for line_name, item in new_snapshot.items():
        old_ids = {s.get("sensor_id") for s in old_snapshot.get(line_name, {}).get("sensors", [])}
        new_sensors = item.get("sensors", [])
        new_ids = {s.get("sensor_id") for s in new_sensors}
        if not old_ids or new_ids - old_ids:
            newly_active.append(item)
    return newly_active



def build_push_payload(new_alarm_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    first = new_alarm_items[0]
    first_sensor = first.get("sensors", [{}])[0] if first.get("sensors") else {}
    label = sensor_label(first_sensor)

    if len(new_alarm_items) == 1:
        title = f"⚠️ PORUCHA: {first['line']}"
        body = f"{first['group_label']} • {label}"
    else:
        title = f"⚠️ Nové poruchy: {len(new_alarm_items)} linek"
        listed = ", ".join(item["line"] for item in new_alarm_items[:4])
        body = listed + ("…" if len(new_alarm_items) > 4 else "")

    return {
        "title": title,
        "body": body,
        "tag": "andon-alarm",
        "url": "/",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }



def send_push_to_all(payload: Dict[str, Any]) -> None:
    if not PUSH_AVAILABLE:
        app.logger.warning("Push vypnuty: pywebpush nelze importovat: %s", PUSH_IMPORT_ERROR)
        return
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        app.logger.warning("Push preskocen: chybi VAPID klice.")
        return

    subs = load_subscriptions()
    if not subs:
        return

    remaining: List[Dict[str, Any]] = []
    body = json.dumps(payload, ensure_ascii=False)

    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=body,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_CLAIMS_SUB},
            )
            remaining.append(sub)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status not in (404, 410):
                app.logger.warning("Push error: %s", exc)
                remaining.append(sub)

    save_subscriptions(remaining)



def update_alarm_snapshot_and_notify() -> None:
    global _last_alarm_snapshot
    new_snapshot = build_alarm_snapshot(_state)
    new_alarms = diff_new_alarms(_last_alarm_snapshot, new_snapshot)
    _last_alarm_snapshot = new_snapshot
    if new_alarms:
        send_push_to_all(build_push_payload(new_alarms))


@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/api/update", methods=["POST"])
def update():
    try:
        if request.headers.get("X-Secret") != SECRET:
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Invalid JSON"}), 400

        merged = dict(DEFAULT_STATE)
        merged.update(_state)
        merged.update(data)
        merged["received_at"] = datetime.now(timezone.utc).isoformat()

        if not isinstance(merged.get("lines"), dict):
            merged["lines"] = {}
        if not isinstance(merged.get("alarm_lines"), list):
            merged["alarm_lines"] = []

        _state.clear()
        _state.update(merged)
        save_state()
        update_alarm_snapshot_and_notify()
        return jsonify({"ok": True})
    except Exception:
        log_exception("Chyba v /api/update")
        return jsonify({"error": "Internal server error in /api/update"}), 500


@app.route("/api/status", methods=["GET"])
def status():
    try:
        return jsonify(public_state())
    except Exception:
        log_exception("Chyba v /api/status")
        return jsonify({"error": "Internal server error in /api/status"}), 500


@app.route("/api/alarms", methods=["GET"])
def alarms():
    try:
        if not _state.get("timestamp"):
            return jsonify({"error": "Žádná data"}), 503

        alarm_detail = []
        for line_name in _state.get("alarm_lines", []):
            line_info = (_state.get("lines") or {}).get(line_name, {})
            clean = sanitize_line_info(line_info)
            alarm_detail.append({
                "line": line_name,
                "group": infer_group(line_name),
                "group_label": GROUPS.get(infer_group(line_name), infer_group(line_name).title()),
                "alarm_sensors": clean["alarm_sensors"],
            })

        return jsonify({
            "timestamp": _state.get("timestamp"),
            "alarm_count": int(_state.get("alarm_count") or 0),
            "total_lines": int(_state.get("total_lines") or 0),
            "alarms": alarm_detail,
        })
    except Exception:
        log_exception("Chyba v /api/alarms")
        return jsonify({"error": "Internal server error in /api/alarms"}), 500


@app.route("/api/push/public-key", methods=["GET"])
def push_public_key():
    try:
        if not PUSH_AVAILABLE:
            return jsonify({
                "enabled": False,
                "error": "pywebpush není nainstalovaný nebo nejde importovat",
                "detail": PUSH_IMPORT_ERROR,
            }), 503
        if not VAPID_PUBLIC_KEY:
            return jsonify({"enabled": False, "error": "Chybí VAPID_PUBLIC_KEY"}), 503
        if not VAPID_PRIVATE_KEY:
            return jsonify({"enabled": False, "error": "Chybí VAPID_PRIVATE_KEY"}), 503
        return jsonify({"enabled": True, "publicKey": VAPID_PUBLIC_KEY})
    except Exception:
        log_exception("Chyba v /api/push/public-key")
        return jsonify({"enabled": False, "error": "Chyba serveru při čtení VAPID klíče"}), 500


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    try:
        sub = request.get_json(force=True, silent=True)
        if not isinstance(sub, dict) or "endpoint" not in sub:
            return jsonify({"error": "Invalid subscription"}), 400

        subs = load_subscriptions()
        endpoint = sub.get("endpoint")
        if not any(s.get("endpoint") == endpoint for s in subs):
            subs.append(sub)
            save_subscriptions(subs)
        return jsonify({"ok": True})
    except Exception:
        log_exception("Chyba v /api/push/subscribe")
        return jsonify({"error": "Internal server error in /api/push/subscribe"}), 500


@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    try:
        sub = request.get_json(force=True, silent=True)
        endpoint = (sub or {}).get("endpoint")
        if not endpoint:
            return jsonify({"error": "Missing endpoint"}), 400

        subs = [s for s in load_subscriptions() if s.get("endpoint") != endpoint]
        save_subscriptions(subs)
        return jsonify({"ok": True})
    except Exception:
        log_exception("Chyba v /api/push/unsubscribe")
        return jsonify({"error": "Internal server error in /api/push/unsubscribe"}), 500


@app.route("/manifest.webmanifest", methods=["GET"])
def manifest():
    data = {
        "name": "Andon Monitor",
        "short_name": "Andon",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f1231",
        "theme_color": "#14183a",
        "icons": [],
    }
    resp = make_response(json.dumps(data, ensure_ascii=False))
    resp.headers["Content-Type"] = "application/manifest+json"
    return resp


@app.route("/sw.js", methods=["GET"])
def sw():
    js = r"""
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: 'Andon Monitor', body: event.data ? event.data.text() : 'Nová událost' };
  }

  const title = data.title || 'Andon Monitor';
  const options = {
    body: data.body || 'Nová událost',
    tag: data.tag || 'andon',
    data: { url: data.url || '/' },
    badge: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><circle cx="48" cy="48" r="48" fill="%23ff5a52"/></svg>',
    icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><rect width="96" height="96" rx="20" fill="%2314183a"/><text x="48" y="59" text-anchor="middle" font-size="44" fill="%23ffffff">⚠️</text></svg>',
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if ('focus' in client) {
          if (client.url !== url && 'navigate' in client) {
            client.navigate(url);
          }
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
"""
    resp = make_response(js)
    resp.headers["Content-Type"] = "application/javascript"
    return resp


@app.route("/", methods=["GET"])
def index():
    html = r"""
<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#14183a">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <title>Andon Monitor</title>
  <link rel="manifest" href="/manifest.webmanifest">
  <style>
    :root {
      --bg: #0f1231;
      --panel: #1a1f47;
      --border: rgba(255,255,255,.12);
      --text: #eef3ff;
      --muted: #b6bfd8;
      --ok: #30d67b;
      --danger: #ee5447;
      --row-alarm: rgba(125, 22, 18, .55);
      --assembly: #2487ff;
      --cable: #a94dee;
      --fipg: #ff9f1c;
      --molding: #3ddc73;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #101332, #0b0e25 70%);
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
      padding-bottom: 20px;
    }
    .wrap {
      width: min(960px, calc(100vw - 20px));
      margin: 16px auto;
      padding: 14px;
    }
    .card {
      background: rgba(22, 27, 64, .96);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 8px 30px rgba(0,0,0,.25);
      padding: 16px;
    }
    h1 { margin: 0 0 8px; font-size: 2rem; }
    .sub { color: var(--muted); font-size: .98rem; margin-bottom: 14px; }
    .row, .toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .toolbar { justify-content: space-between; margin-bottom: 14px; }
    .notice {
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(95, 113, 155, .22);
      border: 1px solid var(--border);
      color: var(--text);
    }
    .alarm-banner {
      margin: 16px 0;
      padding: 18px;
      border-radius: 16px;
      font-size: clamp(1.4rem, 3.2vw, 2.2rem);
      font-weight: 700;
      text-align: center;
      background: var(--danger);
      animation: pulse .8s infinite;
    }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.68} }
    .ok-banner {
      margin: 16px 0;
      padding: 14px;
      border-radius: 16px;
      font-weight: 700;
      text-align: center;
      background: rgba(48, 214, 123, .16);
      color: var(--ok);
      border: 1px solid rgba(48,214,123,.28);
    }
    .hidden { display: none !important; }
    .group-label { color: var(--muted); margin: 14px 0 8px; font-size: 1rem; }
    .chip {
      border: 2px solid rgba(255,255,255,.16);
      color: #fff;
      background: transparent;
      padding: 10px 18px;
      border-radius: 999px;
      font-size: 1.05rem;
      cursor: pointer;
      opacity: .92;
    }
    .chip.active[data-group="assembly"] { background: rgba(36,135,255,.18); border-color: var(--assembly); }
    .chip.active[data-group="cable"] { background: rgba(169,77,238,.18); border-color: var(--cable); }
    .chip.active[data-group="fipg"] { background: rgba(255,159,28,.18); border-color: var(--fipg); }
    .chip.active[data-group="molding"] { background: rgba(61,220,115,.18); border-color: var(--molding); }
    .chip[data-group="assembly"] { border-color: var(--assembly); }
    .chip[data-group="cable"] { border-color: var(--cable); }
    .chip[data-group="fipg"] { border-color: var(--fipg); }
    .chip[data-group="molding"] { border-color: var(--molding); }
    .btn {
      background: #3eb86a;
      color: #fff;
      border: none;
      border-radius: 12px;
      padding: 12px 18px;
      font-size: 1rem;
      cursor: pointer;
    }
    .btn.secondary { background: #5d6ea5; }
    .btn.warn { background: #ff9f1c; color: #111; }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
      overflow: hidden;
    }
    thead th {
      text-align: left;
      color: #fff;
      font-size: clamp(1.05rem, 2vw, 1.35rem);
      padding: 12px 10px;
      border-bottom: 1px solid var(--border);
    }
    tbody td {
      padding: 12px 10px;
      font-size: clamp(1rem, 1.9vw, 1.25rem);
      border-bottom: 1px solid rgba(255,255,255,.08);
      vertical-align: middle;
    }
    tbody tr.alarm-row { background: var(--row-alarm); }
    .status-ok { color: var(--ok); font-weight: 700; }
    .status-alarm { color: var(--danger); font-weight: 700; }
    .line { font-weight: 700; min-width: 84px; }
    .sensor-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 4px 10px;
      border-radius: 999px;
      font-weight: 700;
      margin-right: 8px;
    }
    .sensor-badge.tl { background: rgba(255, 191, 0, .18); color: #ffd34d; }
    .sensor-badge.h { background: rgba(255, 82, 82, .18); color: #ff7f7f; }
    .led {
      width: 14px; height: 14px; border-radius: 50%; display: inline-block;
      box-shadow: 0 0 12px currentColor;
    }
    .led.ok { color: #84ff89; background: #84ff89; }
    .led.h { color: #ff4d4d; background: #ff4d4d; }
    .led.tl { color: #ffc933; background: #ffc933; }
    .footnote { margin-top: 14px; color: var(--muted); font-size: .95rem; }
    .error { color: #ff9f9f; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>🏭 Andon Monitor</h1>
      <div class="sub"><span style="color:#37d36a">●</span> Update: <span id="updatedAt">Načítám…</span></div>

      <div class="toolbar">
        <div class="notice" id="pushInfo">🔔 Push notifikace nejsou aktivní</div>
        <div class="row">
          <button class="btn warn" id="enableSoundBtn">Zapnout zvuk</button>
          <button class="btn" id="enablePushBtn">Zapnout notifikace</button>
          <button class="btn secondary hidden" id="disablePushBtn">Vypnout notifikace</button>
        </div>
      </div>

      <div class="footnote" id="iosHint">
        Na iPhonu: otevři stránku v Safari → Sdílet → Přidat na plochu. Pak ji spusť z plochy a teprve potom zapni notifikace.
      </div>

      <div style="margin-top:16px">
        <div class="group-label">Zobrazit:</div>
        <div class="row" id="groupButtons"></div>
      </div>

      <div class="alarm-banner hidden" id="alarmBanner">⚠️ PORUCHA</div>
      <div class="ok-banner hidden" id="okBanner">✅ Sledované linky OK</div>

      <table>
        <thead>
          <tr>
            <th style="width:58px"></th>
            <th>Linka</th>
            <th>Typ</th>
            <th>Stav</th>
          </tr>
        </thead>
        <tbody id="tbody">
          <tr><td colspan="4">Načítám…</td></tr>
        </tbody>
      </table>

      <div class="footnote" id="debugText"></div>
    </div>
  </div>

  <script>
    const GROUPS = ['assembly', 'cable', 'fipg', 'molding'];
    const STORAGE_KEY = 'andon-visible-groups';
    const SOUND_KEY = 'andon-sound-enabled';
    let currentVisibleGroups = loadVisibleGroups();
    let soundEnabled = localStorage.getItem(SOUND_KEY) === '1';
    let lastAlarmSignature = '';
    let lastSoundSignature = '';
    let pollTimer = null;
    let audioCtx = null;
    let alarmTimer = null;

    function loadVisibleGroups() {
      try {
        const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
        if (Array.isArray(saved) && saved.length) return saved;
      } catch (e) {}
      return ['assembly', 'cable', 'fipg', 'molding'];
    }

    function saveVisibleGroups() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(currentVisibleGroups));
    }

    function groupLabel(group) {
      return {
        assembly: 'Assembly',
        cable: 'Cable',
        fipg: 'FIPG',
        molding: 'Molding',
      }[group] || group;
    }

    function renderGroupButtons() {
      const root = document.getElementById('groupButtons');
      root.innerHTML = '';
      GROUPS.forEach(group => {
        const btn = document.createElement('button');
        btn.className = 'chip ' + (currentVisibleGroups.includes(group) ? 'active' : '');
        btn.dataset.group = group;
        btn.textContent = groupLabel(group);
        btn.onclick = () => {
          if (currentVisibleGroups.includes(group)) {
            if (currentVisibleGroups.length === 1) return;
            currentVisibleGroups = currentVisibleGroups.filter(x => x !== group);
          } else {
            currentVisibleGroups.push(group);
          }
          saveVisibleGroups();
          renderGroupButtons();
          refresh();
        };
        root.appendChild(btn);
      });
    }

    function updateSoundButton() {
      const btn = document.getElementById('enableSoundBtn');
      btn.textContent = soundEnabled ? 'Zvuk zapnutý' : 'Zapnout zvuk';
      btn.classList.toggle('secondary', soundEnabled);
      btn.classList.toggle('warn', !soundEnabled);
    }

    async function enableSound() {
      try {
        audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
        await audioCtx.resume();
        soundEnabled = true;
        localStorage.setItem(SOUND_KEY, '1');
        updateSoundButton();
        beepOnce();
      } catch (e) {
        alert('Nepodařilo se aktivovat zvuk.');
      }
    }

    function beepOnce() {
      if (!soundEnabled || !audioCtx) return;
      try {
        [0, 0.25, 0.5].forEach(delay => {
          const osc = audioCtx.createOscillator();
          const gain = audioCtx.createGain();
          osc.type = 'sawtooth';
          osc.frequency.setValueAtTime(980, audioCtx.currentTime + delay);
          osc.frequency.setValueAtTime(720, audioCtx.currentTime + delay + 0.12);
          osc.connect(gain);
          gain.connect(audioCtx.destination);
          gain.gain.setValueAtTime(0, audioCtx.currentTime + delay);
          gain.gain.linearRampToValueAtTime(0.22, audioCtx.currentTime + delay + 0.02);
          gain.gain.linearRampToValueAtTime(0, audioCtx.currentTime + delay + 0.22);
          osc.start(audioCtx.currentTime + delay);
          osc.stop(audioCtx.currentTime + delay + 0.24);
        });
      } catch (e) {}
    }

    function startAlarmLoop(signature) {
      stopAlarmLoop();
      lastSoundSignature = signature;
      beepOnce();
      alarmTimer = setInterval(beepOnce, 2000);
    }

    function stopAlarmLoop() {
      if (alarmTimer) {
        clearInterval(alarmTimer);
        alarmTimer = null;
      }
      lastSoundSignature = '';
    }

    function fmtStamp(iso) {
      if (!iso) return 'Žádná data';
      try {
        return new Date(iso).toLocaleString('cs-CZ');
      } catch (e) {
        return iso;
      }
    }

    function visibleLine(line) {
      return currentVisibleGroups.includes(line.group);
    }

    function sensorHtml(sensor) {
      const label = sensor.label || (sensor.type === 'teamleader' ? 'TL' : 'H');
      const cls = label === 'TL' ? 'tl' : 'h';
      return `<span class="sensor-badge ${cls}"><span class="led ${cls}"></span>${label}</span>`;
    }

    async function refresh() {
      const res = await fetch('/api/status', { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Nepodařilo se načíst data');

      document.getElementById('updatedAt').textContent = fmtStamp(data.received_at || data.timestamp);
      document.getElementById('debugText').textContent = '';

      const tbody = document.getElementById('tbody');
      tbody.innerHTML = '';

      let visibleAlarmLines = [];
      const lines = Object.entries(data.lines || {});

      if (!lines.length) {
        tbody.innerHTML = '<tr><td colspan="4">Žádná data</td></tr>';
        document.getElementById('alarmBanner').classList.add('hidden');
        document.getElementById('okBanner').classList.remove('hidden');
        stopAlarmLoop();
        return;
      }

      for (const [lineName, lineInfo] of lines) {
        if (!visibleLine(lineInfo)) continue;

        if (lineInfo.alarm) visibleAlarmLines.push(lineName);
        const tr = document.createElement('tr');
        tr.className = lineInfo.alarm ? 'alarm-row' : '';

        const activeSensors = (lineInfo.alarm_sensors || []).filter(s => Number(s.value || 0) === 1);
        let sensorCell = activeSensors.map(sensorHtml).join(' ');
        if (!sensorCell) sensorCell = '—';

        const ledClass = activeSensors.some(s => (s.label || '') === 'TL') ? 'tl' : (lineInfo.alarm ? 'h' : 'ok');

        tr.innerHTML = `
          <td>${lineInfo.alarm ? '<span class="led ' + ledClass + '"></span>' : '<span class="led ok"></span>'}</td>
          <td class="line">${lineName}</td>
          <td>${sensorCell}</td>
          <td class="${lineInfo.alarm ? 'status-alarm' : 'status-ok'}">${lineInfo.alarm ? 'PORUCHA' : 'OK'}</td>
        `;
        tbody.appendChild(tr);
      }

      if (!tbody.children.length) {
        tbody.innerHTML = '<tr><td colspan="4">Pro vybrané skupiny nejsou žádné linky.</td></tr>';
      }

      const banner = document.getElementById('alarmBanner');
      const okBanner = document.getElementById('okBanner');
      const signature = visibleAlarmLines.join('|');
      lastAlarmSignature = signature;

      if (visibleAlarmLines.length) {
        banner.textContent = visibleAlarmLines.length === 1
          ? `⚠️ PORUCHA: ${visibleAlarmLines[0]}`
          : `⚠️ PORUCHY: ${visibleAlarmLines.join(', ')}`;
        banner.classList.remove('hidden');
        okBanner.classList.add('hidden');
        if (soundEnabled && signature !== lastSoundSignature) {
          startAlarmLoop(signature);
        }
      } else {
        banner.classList.add('hidden');
        okBanner.classList.remove('hidden');
        stopAlarmLoop();
      }
    }

    function urlBase64ToUint8Array(base64String) {
      const padding = '='.repeat((4 - base64String.length % 4) % 4);
      const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
      const rawData = atob(base64);
      return Uint8Array.from([...rawData].map(char => char.charCodeAt(0)));
    }

    function isIos() {
      return /iphone|ipad|ipod/i.test(navigator.userAgent);
    }

    function isStandalone() {
      return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    }

    async function getExistingSubscription() {
      if (!('serviceWorker' in navigator)) return null;
      const reg = await navigator.serviceWorker.ready;
      return reg.pushManager.getSubscription();
    }

    async function refreshPushUi() {
      const info = document.getElementById('pushInfo');
      const enableBtn = document.getElementById('enablePushBtn');
      const disableBtn = document.getElementById('disablePushBtn');

      let sub = null;
      try { sub = await getExistingSubscription(); } catch (e) {}

      if (sub && Notification.permission === 'granted') {
        info.textContent = '🔔 Push notifikace zapnuté';
        enableBtn.classList.add('hidden');
        disableBtn.classList.remove('hidden');
      } else {
        info.textContent = '🔔 Push notifikace nejsou aktivní';
        enableBtn.classList.remove('hidden');
        disableBtn.classList.add('hidden');
      }
    }

    async function enablePush() {
      try {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
          alert('Tento prohlížeč nepodporuje push notifikace.');
          return;
        }

        if (isIos() && !isStandalone()) {
          alert('Na iPhonu nejdřív přidej tuto stránku na plochu a spusť ji z ikony na ploše.');
          return;
        }

        const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
        const keyRes = await fetch('/api/push/public-key', { cache: 'no-store' });
        const keyData = await keyRes.json();
        if (!keyRes.ok || !keyData.publicKey) {
          alert(keyData.error || 'Na serveru nejsou funkční push notifikace.');
          return;
        }

        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
          alert('Notifikace nebyly povoleny.');
          return;
        }

        let sub = await reg.pushManager.getSubscription();
        if (!sub) {
          sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(keyData.publicKey),
          });
        }

        const saveRes = await fetch('/api/push/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(sub),
        });
        const saveData = await saveRes.json();
        if (!saveRes.ok) {
          alert(saveData.error || 'Nepodařilo se uložit push odběr.');
          return;
        }

        await refreshPushUi();
        alert('Push notifikace jsou zapnuté.');
      } catch (e) {
        alert('Chyba při zapínání notifikací: ' + (e && e.message ? e.message : e));
      }
    }

    async function disablePush() {
      try {
        const sub = await getExistingSubscription();
        if (sub) {
          await fetch('/api/push/unsubscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ endpoint: sub.endpoint }),
          });
          await sub.unsubscribe();
        }
        await refreshPushUi();
      } catch (e) {
        alert('Chyba při vypínání notifikací.');
      }
    }

    async function start() {
      renderGroupButtons();
      updateSoundButton();
      document.getElementById('enableSoundBtn').addEventListener('click', enableSound);
      document.getElementById('enablePushBtn').addEventListener('click', enablePush);
      document.getElementById('disablePushBtn').addEventListener('click', disablePush);
      if (!isIos()) document.getElementById('iosHint').classList.add('hidden');

      await refreshPushUi();
      await refresh();
      pollTimer = setInterval(() => refresh().catch(err => {
        document.getElementById('debugText').textContent = 'Chyba načítání: ' + (err.message || err);
        document.getElementById('debugText').className = 'footnote error';
      }), 2000);
    }

    start().catch(err => {
      document.getElementById('debugText').textContent = 'Start selhal: ' + (err.message || err);
      document.getElementById('debugText').className = 'footnote error';
    });
  </script>
</body>
</html>
    """
    return html


load_state()
_last_alarm_snapshot = build_alarm_snapshot(_state)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
