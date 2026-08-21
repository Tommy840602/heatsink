from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock


METRICS = """# HELP thermoform_cae_observability_healthy Whether durable CAE recovery is healthy.
# TYPE thermoform_cae_observability_healthy gauge
thermoform_cae_observability_healthy 0
# HELP thermoform_cae_watchdog_present Whether a durable watchdog audit exists.
# TYPE thermoform_cae_watchdog_present gauge
thermoform_cae_watchdog_present 0
thermoform_cae_watchdog_age_seconds 0
thermoform_cae_resume_stale_heartbeats 0
thermoform_cae_resume_active_heartbeats 0
thermoform_cae_resume_orphan_repairs 0
thermoform_cae_resume_failed_retry_attempts 0
thermoform_cae_watchdog_last_orphan_repairs 0
thermoform_cae_watchdog_last_active_attempts 0
thermoform_cae_watchdog_last_pending_grace_attempts 0
"""
PHASE = 0
PHASE_LOCK = Lock()


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path not in {"/", "/metrics"}:
            self.send_error(404)
            return
        with PHASE_LOCK:
            phase = PHASE
        body = (
            METRICS
            + "# HELP thermoform_observability_drill_phase Active HA drill phase.\n"
            + "# TYPE thermoform_observability_drill_phase gauge\n"
            + f"thermoform_observability_drill_phase {phase}\n"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        global PHASE
        if self.path not in {"/phase/1", "/phase/2", "/phase/3"}:
            self.send_error(404)
            return
        with PHASE_LOCK:
            PHASE = int(self.path.rsplit("/", 1)[1])
        self.send_response(204)
        self.end_headers()

    def log_message(self, _format, *_args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), MetricsHandler).serve_forever()
