import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from threading import Lock


EXPECTED_AUTHORIZATION = os.environ["EXPECTED_AUTHORIZATION"]
DELIVERIES = []
DELIVERIES_LOCK = Lock()
MAX_BODY_BYTES = 1_048_576


class ReceiverHandler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/deliveries":
            self.send_error(404)
            return
        with DELIVERIES_LOCK:
            deliveries = list(DELIVERIES)
        self.send_json(200, {"deliveries": deliveries})

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/v1/thermoform":
            self.send_error(404)
            return
        authorization = self.headers.get("Authorization", "")
        if not hmac.compare_digest(authorization, EXPECTED_AUTHORIZATION):
            self.send_json(401, {"error": "invalid authorization"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "invalid content length"})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self.send_json(413, {"error": "invalid payload size"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "invalid json"})
            return
        alerts = payload.get("alerts")
        if payload.get("version") != "4" or not isinstance(alerts, list):
            self.send_json(422, {"error": "invalid Alertmanager payload"})
            return
        delivery = {
            "receiver": payload.get("receiver"),
            "status": payload.get("status"),
            "groupKey": payload.get("groupKey"),
            "alertnames": [alert.get("labels", {}).get("alertname") for alert in alerts],
        }
        with DELIVERIES_LOCK:
            DELIVERIES.append(delivery)
        self.send_json(200, {"accepted": True})

    def log_message(self, _format, *_args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), ReceiverHandler).serve_forever()
