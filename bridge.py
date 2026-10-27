import json
import threading
import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer, StreamRequestHandler

HTTP_PORT = 8000
TCP_PORT  = 5000

data_lock = threading.Lock()

# Automatically use the folder where bridge.py and index.html are located
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

latest_data = {
    "cycle": 0,
    "source": "WAITING_FOR_QNX",
    "patients": [
        {
            "id": i,
            "spo2": 98,
            "hr": 80,
            "rr": 16,
            "temp": 36.8,
            "fall": False,
            "status": "NORMAL",
            "priority": 0,
            "reason": "Waiting for QNX data"
        }
        for i in range(1, 5)
    ]
}


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=CURRENT_DIR, **kwargs)

    def do_GET(self):
        # Handle /api/data endpoint
        if self.path.split("?")[0] == "/api/data":
            with data_lock:
                payload = json.dumps(latest_data).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            # CORS header so browsers never block the request
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path.split("?")[0] == "/":
            self.path = "/index.html"

        super().do_GET()

    def log_message(self, fmt, *args):
        # Clean terminal logging
        print("[HTTP]", fmt % args)


class QNXDataHandler(StreamRequestHandler):
    def handle(self):
        client = self.client_address
        print("--> [QNX CONNECTED] Client address:", client)

        try:
            while True:
                # QNX sends one JSON object terminated by \n
                line = self.rfile.readline(65536)

                if not line:
                    break

                try:
                    incoming = json.loads(line.decode("utf-8"))

                    # Basic structural checks
                    if not isinstance(incoming, dict):
                        raise ValueError("JSON root must be an object")

                    if not isinstance(incoming.get("patients"), list):
                        raise ValueError("'patients' must be a list")

                    if len(incoming["patients"]) != 4:
                        raise ValueError("Expected exactly 4 patients")

                    with data_lock:
                        latest_data.clear()
                        latest_data.update(incoming)

                    print(
                        f"--> [QNX SYNC] Received Cycle #{incoming.get('cycle')} | Source: {incoming.get('source')}"
                    )

                    self.wfile.write(b"OK\n")
                    self.wfile.flush()

                except (ValueError, UnicodeDecodeError) as error:
                    print("[REJECTED] Bad data frame:", error)
                    self.wfile.write(b"ERROR\n")
                    self.wfile.flush()

        except (ConnectionError, OSError) as error:
            print("[DISCONNECTED] Client connection ended:", error)

        print("<-- [QNX DISCONNECTED] Client address:", client)


class ReusableTCPServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print("=" * 60)
    print(" MediSentinel Edge Telemetry Bridge Starting...")
    print(f" Dashboard URL : http://127.0.0.1:{HTTP_PORT}")
    print(f" Data API URL  : http://127.0.0.1:{HTTP_PORT}/api/data")
    print(f" QNX TCP Port  : {TCP_PORT}")
    print(f" Serving HTML  : {CURRENT_DIR}")
    print(" Waiting for QNX Raspberry Pi data...")
    print("=" * 60)

    http_server = ThreadingHTTPServer(
        ("0.0.0.0", HTTP_PORT),
        DashboardHandler
    )

    tcp_server = ReusableTCPServer(
        ("0.0.0.0", TCP_PORT),
        QNXDataHandler
    )

    threading.Thread(
        target=http_server.serve_forever,
        daemon=True
    ).start()

    try:
        tcp_server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping bridge...")
    finally:
        tcp_server.server_close()
        http_server.shutdown()
        http_server.server_close()