"""
ANDON BOARD SCRAPER
- posloucha websocket z andonu
- posila aktualni stav na cloud endpointy
- OPRAVA: typy H / TL jsou prohozene podle realneho chovani ve vyrobe
"""

import json
import time
import logging
import threading
from datetime import datetime

import requests

try:
    import websocket
except ImportError:
    print("CHYBA: Chybi modul websocket-client")
    print("Spust instalace.bat / pip install -r requirements.txt")
    raise SystemExit(1)

# ─── KONFIGURACE ──────────────────────────────────────────────────────────────
CLOUD_ENDPOINTS = [
    {
        "url": "https://andon-monitor-production.up.railway.app/api/update",
        "secret": "HiLex2024Andon",
        "name": "Railway",
    },
    {
        "url": "https://workhilex.pythonanywhere.com/api/update",
        "secret": "HiLex2024Andon",
        "name": "PythonAnywhere",
    },
]

HEARTBEAT_SEC = 30
WS_URL = "ws://hlczaps04:8080/ctt-rec/websocket"
WS_ORIGIN = "http://hlczaps04:8080"

# ─── MAPOVANI SENZORU NA LINKY ────────────────────────────────────────────────
SENSOR_TO_LINE = {
    "a0110": "A01", "a0120": "A01", "a0130": "A01", "a0140": "A01", "a0150": "A01", "a0160": "A01", "a0170": "A01",
    "a0210": "A02", "a0220": "A02", "a0230": "A02", "a0240": "A02", "a0250": "A02", "a0260": "A02", "a0270": "A02",
    "a0310": "A03", "a0320": "A03", "a0330": "A03", "a0340": "A03",
    "a0410": "A04", "a0420": "A04", "a0430": "A04", "a0440": "A04",
    "a0510": "A05", "a0520": "A05", "a0530": "A05", "a0540": "A05",
    "a0610": "A06", "a0620": "A06", "a0630": "A06", "a0640": "A06",
    "a0710": "A07", "a0720": "A07", "a0730": "A07", "a0740": "A07", "a0750": "A07",
    "a0810": "A08", "a0820": "A08", "a0830": "A08", "a0840": "A08", "a0850": "A08",
    "@c01.": "C01", "@c02.": "C02", "@c03.": "C03", "@c04.": "C04",
    "@f01.": "F01", "@f02.": "F02", "@f03.": "F03",
    "@m01.": "M01", "@m02.": "M02", "@m03.": "M03", "@m04.": "M04", "@m05.": "M05", "@m06.": "M06",
}

ALL_LINES = sorted(set(SENSOR_TO_LINE.values()))
line_states = {ln: {"alarm": False, "sensors": {}} for ln in ALL_LINES}
cloud_queue = threading.Event()

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ─── POMOCNE FUNKCE ───────────────────────────────────────────────────────────
def find_line(sensor_id: str):
    sid = (sensor_id or "").lower()
    for key, line in SENSOR_TO_LINE.items():
        if key in sid:
            return line
    return None

def sensor_type_from_id(sensor_id: str) -> str:
    """
    OPRAVA:
    Realita ve vyrobe je obracene oproti puvodni logice:
    - kdyz se zmackne zlute TL, drive se ukazovalo cervene H
    - kdyz se zmackne cervene H, drive se ukazovalo zlute TL

    Proto typy otacime.
    """
    sid = (sensor_id or "").lower()
    return "comp" if "teamleader" in sid else "teamleader"

def build_payload():
    alarm_lines = [ln for ln, state in line_states.items() if state["alarm"]]
    lines_payload = {}

    for ln, state in line_states.items():
        active = [
            {"sensor_id": sid, **info}
            for sid, info in state["sensors"].items()
            if float(info.get("value", 0) or 0) == 1.0
        ]
        lines_payload[ln] = {
            "alarm": state["alarm"],
            "alarm_sensors": active,
        }

    return {
        "timestamp": datetime.now().isoformat(),
        "lines": lines_payload,
        "alarm_lines": alarm_lines,
        "alarm_count": len(alarm_lines),
        "total_lines": len(line_states),
    }

def send_to_cloud():
    payload = build_payload()

    for ep in CLOUD_ENDPOINTS:
        for attempt in range(3):
            try:
                resp = requests.post(
                    ep["url"],
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Secret": ep["secret"],
                    },
                    timeout=5,
                )
                resp.raise_for_status()

                alarms = payload["alarm_lines"]
                if alarms:
                    log.warning("[%s] OK – PORUCHY: %s", ep["name"], ", ".join(alarms))
                else:
                    log.info("[%s] OK – vse v poradku", ep["name"])
                break
            except Exception as e:
                log.error("[%s] Chyba (pokus %s/3): %s", ep["name"], attempt + 1, e)
                time.sleep(1)

def cloud_worker():
    while True:
        cloud_queue.wait(timeout=HEARTBEAT_SEC)
        cloud_queue.clear()
        send_to_cloud()

# ─── ZPRACOVANI WS ZPRAV ──────────────────────────────────────────────────────
def process_message(params):
    sensor_id = params.get("sensorid", "")
    if "workplace_request" not in sensor_id:
        return

    try:
        value = float(params.get("value", -1))
    except Exception:
        return

    sen_type = sensor_type_from_id(sensor_id)
    ts = params.get("time", datetime.now().isoformat())
    line = find_line(sensor_id)
    if not line:
        return

    line_states[line]["sensors"][sensor_id] = {
        "value": value,
        "type": sen_type,
        "time": ts,
    }

    any_alarm = any(float(s.get("value", 0) or 0) == 1.0 for s in line_states[line]["sensors"].values())
    prev_alarm = line_states[line]["alarm"]
    line_states[line]["alarm"] = any_alarm

    stroj = sensor_id.split("@")[1].split(".")[0].upper() if "@" in sensor_id else sensor_id

    if value == 1.0:
        typ = "TeamLeader" if sen_type == "teamleader" else "Porucha"
        log.warning("*** ALARM [%s]: %s | %s", typ, line, stroj)
        cloud_queue.set()
    elif value == 0.0 and prev_alarm and not any_alarm:
        log.info("Alarm VYRESENY: %s", line)
        cloud_queue.set()

# ─── WEBSOCKET ────────────────────────────────────────────────────────────────
def on_open(ws):
    log.info("WebSocket pripojeny – cekam na poruchy...")

def on_message(ws, message):
    try:
        data = json.loads(message)
        if not isinstance(data, dict):
            return
        params = data.get("params", {})
        if isinstance(params, dict):
            process_message(params)
    except Exception as e:
        log.error("WS chyba: %s", e)

def on_error(ws, error):
    log.error("WS error: %s", error)

def on_close(ws, code, msg):
    log.warning("WS zavreno – restartuji...")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info(" ANDON SCRAPER")
    log.info(" Cloud endpointy:")
    for ep in CLOUD_ENDPOINTS:
        log.info(" - %s: %s", ep["name"], ep["url"])
    log.info(" Heartbeat: %ss | Linek: %s", HEARTBEAT_SEC, len(ALL_LINES))
    log.info("=" * 60)

    threading.Thread(target=cloud_worker, daemon=True).start()
    cloud_queue.set()

    websocket.enableTrace(False)

    while True:
        try:
            ws = websocket.WebSocketApp(
                WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                header={"Origin": WS_ORIGIN},
            )
            ws.run_forever(ping_interval=20, ping_timeout=10, reconnect=5)
        except KeyboardInterrupt:
            log.info("Zastaveno.")
            break
        except Exception as e:
            log.error("Chyba: %s", e)
            time.sleep(3)

if __name__ == "__main__":
    main()
