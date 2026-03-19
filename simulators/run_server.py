"""
Standalone ENIP tag server for testing.

Hosts all tags that both the HMI simulator and the enip_cip_interface
container connect to. No process simulation — tag values are written
by external clients.

Includes a lightweight web UI on port 5556 for viewing live tag values.

Usage:
    uv run python simulators/run_server.py [--port 44818] [--web-port 5556]
"""

import sys
import os
import time
import json
import logging
import argparse
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enip_cip_interface.enip_server import EnipServer, EnipTag

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SERVER] %(levelname)s %(message)s",
)

TAGS = [
    # Pump A
    EnipTag("CS_PumpA_FlowRate", 0.0),
    EnipTag("CS_PumpA_Pressure", 0.0),
    EnipTag("CS_PumpA_Total", 0.0),
    EnipTag("CS_PumpA_Pumping", False),
    EnipTag("CS_PumpA_State", 0.0),
    EnipTag("CS_PumpA_TargetRate", 10.0),
    EnipTag("CS_PumpA_CorrectionFactor", 1.0),
    EnipTag("CS_PumpA_LastCal", 0.0),
    # Pump B
    EnipTag("CS_PumpB_FlowRate", 0.0),
    EnipTag("CS_PumpB_Pressure", 0.0),
    EnipTag("CS_PumpB_Total", 0.0),
    EnipTag("CS_PumpB_Pumping", False),
    EnipTag("CS_PumpB_State", 0.0),
    EnipTag("CS_PumpB_TargetRate", 10.0),
    EnipTag("CS_PumpB_CorrectionFactor", 1.0),
    EnipTag("CS_PumpB_LastCal", 0.0),
    # Tanks
    EnipTag("CS_TankA_Level", 50.0),
    EnipTag("CS_TankB_Level", 50.0),
    # Valves
    EnipTag("CS_ValveA_Open", False),
    EnipTag("CS_ValveB_Open", False),
]

# Reference set by main(), read by the HTTP handler
server_ref: EnipServer = None
# Thread-safe snapshot of current tag values, updated by main loop
tag_snapshot = {}
tag_snapshot_lock = threading.Lock()


class TagHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress request logs

    def do_GET(self):
        if self.path == "/api/tags":
            with tag_snapshot_lock:
                data = dict(tag_snapshot)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode())


HTML_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ENIP Server — Tag Viewer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
         background: #0d1117; color: #e0e0e0; padding: 20px; }
  h1 { color: #58a6ff; margin-bottom: 4px; font-size: 20px; }
  .subtitle { color: #555; font-size: 12px; margin-bottom: 16px; }
  .status { font-size: 12px; color: #888; margin-bottom: 16px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
         margin-right: 6px; background: #444; }
  .dot.ok { background: #3fb950; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .panel { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 14px; }
  .panel h2 { font-size: 12px; color: #58a6ff; margin-bottom: 10px; text-transform: uppercase;
              letter-spacing: 1px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 10px; color: #484f58; text-transform: uppercase;
       letter-spacing: 1px; padding: 4px 8px; border-bottom: 1px solid #30363d; }
  td { padding: 4px 8px; font-size: 13px; font-family: monospace; border-bottom: 1px solid #161b22; }
  td.name { color: #8b949e; }
  td.val { color: #3fb950; text-align: right; }
  td.val.stale { color: #484f58; }
  td.val.changed { color: #f0883e; }
  .updated { font-size: 11px; color: #484f58; margin-top: 8px; text-align: right; }
</style>
</head>
<body>
<h1>ENIP Tag Server</h1>
<div class="subtitle">Live tag values from cpppo server</div>
<div class="status"><span class="dot" id="dot"></span><span id="st">Loading...</span></div>

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
<div class="updated" id="ts"></div>

<script>
let prev = {};

function fmt(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "ON" : "OFF";
  if (typeof v === "number") return v % 1 === 0 ? v.toString() : v.toFixed(3);
  return String(v);
}

function short(t) { return t.replace(/^CS_/, ""); }

function render(tbody, tags, data) {
  let html = "";
  for (const t of tags) {
    const v = data[t];
    const changed = prev[t] !== undefined && prev[t] !== v;
    const cls = v === undefined ? "val stale" : changed ? "val changed" : "val";
    html += '<tr><td class="name">' + short(t) + '</td><td class="' + cls + '">' + fmt(v) + '</td></tr>';
  }
  tbody.innerHTML = html;
}

async function poll() {
  try {
    const r = await fetch("/api/tags");
    const data = await r.json();
    document.getElementById("dot").className = "dot ok";
    document.getElementById("st").textContent = "Serving " + Object.keys(data).length + " tags";

    render(document.getElementById("pumpA"),
      ["CS_PumpA_FlowRate","CS_PumpA_Pressure","CS_PumpA_Total","CS_PumpA_Pumping",
       "CS_PumpA_State","CS_PumpA_TargetRate","CS_PumpA_CorrectionFactor","CS_PumpA_LastCal"], data);
    render(document.getElementById("pumpB"),
      ["CS_PumpB_FlowRate","CS_PumpB_Pressure","CS_PumpB_Total","CS_PumpB_Pumping",
       "CS_PumpB_State","CS_PumpB_TargetRate","CS_PumpB_CorrectionFactor","CS_PumpB_LastCal"], data);
    render(document.getElementById("tanks"), ["CS_TankA_Level","CS_TankB_Level"], data);
    render(document.getElementById("valves"), ["CS_ValveA_Open","CS_ValveB_Open"], data);

    document.getElementById("ts").textContent = "Updated " + new Date().toLocaleTimeString();
    prev = data;
  } catch (e) {
    document.getElementById("dot").className = "dot";
    document.getElementById("st").textContent = "Error fetching tags";
  }
}

setInterval(poll, 1000);
poll();
</script>
</body>
</html>
"""


def run_web_server(port):
    httpd = HTTPServer(("0.0.0.0", port), TagHandler)
    logging.info(f"Tag viewer: http://localhost:{port}")
    httpd.serve_forever()


def main():
    global server_ref

    parser = argparse.ArgumentParser(description="Standalone ENIP tag server")
    parser.add_argument("--port", type=int, default=44818, help="ENIP server port (default: 44818)")
    parser.add_argument("--web-port", type=int, default=5556, help="Web viewer port (default: 5556)")
    args = parser.parse_args()

    logging.info(f"Starting ENIP server on port {args.port} with {len(TAGS)} tags")
    for tag in TAGS:
        logging.info(f"  {tag}")

    server_ref = EnipServer(port=args.port, tags=TAGS)
    logging.info("Server running. Press Ctrl+C to stop.")

    t = threading.Thread(target=run_web_server, args=(args.web_port,), daemon=True)
    t.start()

    try:
        while True:
            # Sync external writes back into local tags
            writes = server_ref.pop_write_operations()
            for w in writes:
                logging.info(f"  WRITE: {w.tag_name} = {w.value}")
                if w.tag_name in server_ref.tags:
                    server_ref.tags[w.tag_name].current_value = w.value

            reads = server_ref.pop_read_operations()
            if reads:
                tag_names = set(r.tag_name for r in reads)
                logging.info(f"  READ: {tag_names}")

            # Push updated values back to shared memory so cpppo serves correct values
            server_ref._sync_shared_tags()

            # Update the snapshot for the web UI every cycle
            with tag_snapshot_lock:
                for name, tag in server_ref.tags.items():
                    tag_snapshot[name] = tag.current_value

            # Log current tag values
            lines = ["  TAG VALUES:"]
            for name, tag in server_ref.tags.items():
                val = tag.current_value
                if isinstance(val, float):
                    lines.append(f"    {name:<35} {val:>12.3f}")
                else:
                    lines.append(f"    {name:<35} {str(val):>12}")
            logging.info("\n".join(lines))

            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down server...")
        server_ref.stop()


if __name__ == "__main__":
    main()
