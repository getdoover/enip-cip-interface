"""
HMI Simulator — Flask web app with pylogix backend.

Connects to the ENIP server and provides a browser UI to:
  - View all tag values (auto-refreshing)
  - Write to CS_PumpA_TargetRate, CS_PumpB_TargetRate, CS_PumpA_State, CS_PumpB_State

Usage:
    uv run python simulators/hmi_simulator.py [--host 127.0.0.1] [--port 44818] [--web-port 5555]
"""

import argparse
import logging
import threading
import time
from flask import Flask, jsonify, request, Response

from pylogix import PLC

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [HMI] %(levelname)s %(message)s",
)

READ_TAGS = [
    "CS_PumpA_FlowRate",
    "CS_PumpA_Pressure",
    "CS_PumpA_Total",
    "CS_PumpA_Pumping",
    "CS_PumpA_State",
    "CS_PumpA_TargetRate",
    "CS_PumpA_CorrectionFactor",
    "CS_PumpA_LastCal",
    "CS_PumpB_FlowRate",
    "CS_PumpB_Pressure",
    "CS_PumpB_Total",
    "CS_PumpB_Pumping",
    "CS_PumpB_State",
    "CS_PumpB_TargetRate",
    "CS_PumpB_CorrectionFactor",
    "CS_PumpB_LastCal",
    "CS_TankA_Level",
    "CS_TankB_Level",
    "CS_ValveA_Open",
    "CS_ValveB_Open",
]

WRITABLE_TAGS = {
    "CS_PumpA_TargetRate": "float",
    "CS_PumpB_TargetRate": "float",
    "CS_PumpA_State": "float",
    "CS_PumpB_State": "float",
}

# Shared state
tag_values = {}
comms_ok = False
tag_lock = threading.Lock()
plc_host = "127.0.0.1"
plc_port = 44818

app = Flask(__name__)


def poll_tags():
    """Background thread: cyclic read of all tags."""
    global tag_values, comms_ok
    while True:
        try:
            with PLC() as comm:
                comm.IPAddress = plc_host
                while True:
                    snapshot = {}
                    any_success = False
                    for tag_name in READ_TAGS:
                        ret = comm.Read(tag_name)
                        if ret.Status == "Success":
                            snapshot[tag_name] = ret.Value
                            any_success = True
                        else:
                            snapshot[tag_name] = None
                    with tag_lock:
                        tag_values = snapshot
                        comms_ok = any_success
                    time.sleep(1)
        except Exception as e:
            logging.error(f"Poll error: {e}, reconnecting in 2s...")
            with tag_lock:
                comms_ok = False
            time.sleep(2)


@app.route("/")
def index():
    return Response(HTML_PAGE, content_type="text/html")


@app.route("/api/tags")
def get_tags():
    with tag_lock:
        return jsonify({"tags": tag_values, "comms_ok": comms_ok})


@app.route("/api/write", methods=["POST"])
def write_tag():
    data = request.json
    tag_name = data.get("tag")
    value = data.get("value")

    if tag_name not in WRITABLE_TAGS:
        return jsonify({"error": f"Tag {tag_name} is not writable"}), 400

    cast = float if WRITABLE_TAGS[tag_name] == "float" else str
    try:
        value = cast(value)
    except (ValueError, TypeError):
        return jsonify({"error": f"Invalid value for {tag_name}"}), 400

    try:
        with PLC() as comm:
            comm.IPAddress = plc_host
            ret = comm.Write(tag_name, value)
            if ret.Status == "Success":
                logging.info(f"WRITE {tag_name} = {value}")
                return jsonify({"ok": True})
            else:
                return jsonify({"error": ret.Status}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


HTML_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>HMI Simulator</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
         background: #1a1a2e; color: #e0e0e0; padding: 20px; }
  h1 { color: #00d4ff; margin-bottom: 4px; font-size: 22px; }
  .subtitle { color: #666; font-size: 13px; margin-bottom: 20px; }
  .status { font-size: 12px; color: #888; margin-bottom: 16px; }
  .status .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
                 margin-right: 6px; background: #444; }
  .status .dot.ok { background: #00e676; }
  .status .dot.err { background: #ff1744; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
  .panel { background: #16213e; border: 1px solid #0f3460; border-radius: 8px; padding: 16px; }
  .panel h2 { font-size: 14px; color: #00d4ff; margin-bottom: 12px; text-transform: uppercase;
              letter-spacing: 1px; }
  .control-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
  .control-row label { flex: 1; font-size: 13px; color: #aaa; }
  .control-row input { width: 90px; padding: 6px 8px; background: #0a0a1a; border: 1px solid #333;
                       border-radius: 4px; color: #fff; font-size: 13px; font-family: monospace; }
  .control-row input:focus { border-color: #00d4ff; outline: none; }
  .control-row button { padding: 6px 14px; background: #0f3460; border: 1px solid #00d4ff;
                        border-radius: 4px; color: #00d4ff; cursor: pointer; font-size: 12px; }
  .control-row button:hover { background: #00d4ff; color: #0a0a1a; }
  .control-row .current { font-size: 13px; color: #00e676; font-family: monospace; min-width: 70px;
                          text-align: right; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 11px; color: #666; text-transform: uppercase;
       letter-spacing: 1px; padding: 6px 8px; border-bottom: 1px solid #333; }
  td { padding: 5px 8px; font-size: 13px; font-family: monospace; border-bottom: 1px solid #1a1a2e; }
  td.tag-name { color: #aaa; }
  td.tag-val { color: #00e676; text-align: right; }
  td.tag-val.err { color: #ff1744; }
  .pump-section { margin-bottom: 0; }
</style>
</head>
<body>
<h1>HMI Simulator</h1>
<div class="subtitle">EtherNet/IP Tag Monitor</div>
<div class="status"><span class="dot" id="statusDot"></span><span id="statusText">Connecting...</span></div>

<div class="grid">
  <div class="panel">
    <h2>Pump A Controls</h2>
    <div class="control-row">
      <label>State</label>
      <span class="current" id="cur_CS_PumpA_State">—</span>
      <input type="number" id="in_CS_PumpA_State" step="1" placeholder="0">
      <button onclick="writeTag('CS_PumpA_State')">Set</button>
    </div>
    <div class="control-row">
      <label>Target Rate</label>
      <span class="current" id="cur_CS_PumpA_TargetRate">—</span>
      <input type="number" id="in_CS_PumpA_TargetRate" step="0.1" placeholder="10.0">
      <button onclick="writeTag('CS_PumpA_TargetRate')">Set</button>
    </div>
  </div>
  <div class="panel">
    <h2>Pump B Controls</h2>
    <div class="control-row">
      <label>State</label>
      <span class="current" id="cur_CS_PumpB_State">—</span>
      <input type="number" id="in_CS_PumpB_State" step="1" placeholder="0">
      <button onclick="writeTag('CS_PumpB_State')">Set</button>
    </div>
    <div class="control-row">
      <label>Target Rate</label>
      <span class="current" id="cur_CS_PumpB_TargetRate">—</span>
      <input type="number" id="in_CS_PumpB_TargetRate" step="0.1" placeholder="10.0">
      <button onclick="writeTag('CS_PumpB_TargetRate')">Set</button>
    </div>
  </div>
</div>

<div class="grid">
  <div class="panel">
    <h2>Pump A</h2>
    <table><thead><tr><th>Tag</th><th style="text-align:right">Value</th></tr></thead>
    <tbody id="pumpA"></tbody></table>
  </div>
  <div class="panel">
    <h2>Pump B</h2>
    <table><thead><tr><th>Tag</th><th style="text-align:right">Value</th></tr></thead>
    <tbody id="pumpB"></tbody></table>
  </div>
</div>

<div class="grid">
  <div class="panel">
    <h2>Tanks</h2>
    <table><thead><tr><th>Tag</th><th style="text-align:right">Value</th></tr></thead>
    <tbody id="tanks"></tbody></table>
  </div>
  <div class="panel">
    <h2>Valves</h2>
    <table><thead><tr><th>Tag</th><th style="text-align:right">Value</th></tr></thead>
    <tbody id="valves"></tbody></table>
  </div>
</div>

<script>
const WRITABLE = ["CS_PumpA_TargetRate","CS_PumpB_TargetRate","CS_PumpA_State","CS_PumpB_State"];

function fmt(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "ON" : "OFF";
  if (typeof v === "number") return v % 1 === 0 ? v.toString() : v.toFixed(2);
  return String(v);
}

function shortName(tag) { return tag.replace(/^CS_/, ""); }

function renderRows(tbody, tags, data) {
  let html = "";
  for (const t of tags) {
    const v = data[t];
    const cls = v === null ? "tag-val err" : "tag-val";
    html += '<tr><td class="tag-name">' + shortName(t) + '</td><td class="' + cls + '">' + fmt(v) + "</td></tr>";
  }
  tbody.innerHTML = html;
}

function updateCurrents(data) {
  for (const tag of WRITABLE) {
    const el = document.getElementById("cur_" + tag);
    if (el) el.textContent = fmt(data[tag]);
  }
}

async function poll() {
  try {
    const r = await fetch("/api/tags");
    const resp = await r.json();
    const data = resp.tags;
    const ok = resp.comms_ok;

    document.getElementById("statusDot").className = ok ? "dot ok" : "dot err";
    document.getElementById("statusText").textContent = ok ? "ENIP Connected" : "ENIP No Comms";

    renderRows(document.getElementById("pumpA"),
      ["CS_PumpA_FlowRate","CS_PumpA_Pressure","CS_PumpA_Total","CS_PumpA_Pumping",
       "CS_PumpA_State","CS_PumpA_TargetRate","CS_PumpA_CorrectionFactor","CS_PumpA_LastCal"], data);
    renderRows(document.getElementById("pumpB"),
      ["CS_PumpB_FlowRate","CS_PumpB_Pressure","CS_PumpB_Total","CS_PumpB_Pumping",
       "CS_PumpB_State","CS_PumpB_TargetRate","CS_PumpB_CorrectionFactor","CS_PumpB_LastCal"], data);
    renderRows(document.getElementById("tanks"),
      ["CS_TankA_Level","CS_TankB_Level"], data);
    renderRows(document.getElementById("valves"),
      ["CS_ValveA_Open","CS_ValveB_Open"], data);
    updateCurrents(data);
  } catch (e) {
    document.getElementById("statusDot").className = "dot err";
    document.getElementById("statusText").textContent = "Web UI connection error";
  }
}

async function writeTag(tag) {
  const input = document.getElementById("in_" + tag);
  const value = parseFloat(input.value);
  if (isNaN(value)) return;
  try {
    const r = await fetch("/api/write", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({tag, value})
    });
    const data = await r.json();
    if (data.ok) input.value = "";
  } catch (e) {
    alert("Write failed: " + e);
  }
}

setInterval(poll, 1000);
poll();
</script>
</body>
</html>
"""


def main():
    global plc_host, plc_port

    parser = argparse.ArgumentParser(description="HMI Simulator — Flask web UI")
    parser.add_argument("--host", default="127.0.0.1", help="ENIP server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=44818, help="ENIP server port (default: 44818)")
    parser.add_argument("--web-port", type=int, default=5555, help="Flask web UI port (default: 5555)")
    args = parser.parse_args()

    plc_host = args.host
    plc_port = args.port

    logging.info(f"ENIP server: {plc_host}:{plc_port}")
    logging.info(f"Web UI: http://localhost:{args.web_port}")

    t = threading.Thread(target=poll_tags, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=args.web_port, debug=False)


if __name__ == "__main__":
    main()
