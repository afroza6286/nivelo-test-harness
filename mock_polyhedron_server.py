"""Local HTTP double implementing the Polyhedron bills and ledger endpoints.

Run directly with ``python mock_polyhedron_server.py --port 8089``. A JSON
configuration may provide ``bills_by_payment``, ``bill_actions`` and
``ledger_actions``. Actions are queued objects, for example
``{"type": "status", "status": 500}`` or
``{"type": "timeout", "seconds": 2}``, to simulate transient failures.
"""

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse


class MockPolyhedronState:
    """Mutable data and request history shared by the server's request threads."""

    def __init__(
        self,
        bills_by_payment: Optional[Dict[str, List[dict]]] = None,
        bill_actions: Optional[Dict[str, List[dict]]] = None,
        ledger_actions: Optional[List[dict]] = None,
    ) -> None:
        self.bills_by_payment = bills_by_payment or {}
        self.bill_actions = {key: list(value) for key, value in (bill_actions or {}).items()}
        self.ledger_actions = list(ledger_actions or [])
        self.requests: List[dict] = []
        self.ledger_entries: List[dict] = []
        self._lock = threading.Lock()

    def take_action(self, queue: List[dict]) -> Optional[dict]:
        with self._lock:
            return queue.pop(0) if queue else None

    def take_bill_action(self, payment_id: str) -> Optional[dict]:
        with self._lock:
            queue = self.bill_actions.get(payment_id, [])
            return queue.pop(0) if queue else None

    def record_request(self, entry: dict) -> None:
        with self._lock:
            self.requests.append(entry)

    def record_ledger_entry(self, entry: dict) -> None:
        with self._lock:
            self.ledger_entries.append(entry)


class MockPolyhedronServer:
    """Context-managed threaded server for local contract and failure tests."""

    def __init__(
        self,
        state: Optional[MockPolyhedronState] = None,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.state = state or MockPolyhedronState()
        handler = self._handler_for(self.state)
        self._server = ThreadingHTTPServer((host, port), handler)
        self._server.daemon_threads = True
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return "http://{}:{}/api".format(host, port)

    def start(self) -> "MockPolyhedronServer":
        if self._thread is None:
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
        return self

    def close(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=2)
            self._thread = None
        self._server.server_close()

    def __enter__(self) -> "MockPolyhedronServer":
        return self.start()

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    @staticmethod
    def _handler_for(state: MockPolyhedronState):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format_string: str, *args: Any) -> None:
                return

            def send_json(self, status: int, value: Any) -> None:
                body = json.dumps(value).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def perform_action(self, action: Optional[dict]) -> bool:
                if not action:
                    return False
                if action.get("type") == "timeout":
                    time.sleep(float(action.get("seconds", 1)))
                    return False
                if action.get("type") == "status":
                    self.send_json(int(action.get("status", 500)), {"error": "simulated failure"})
                    return True
                return False

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self.send_json(200, {"status": "ok"})
                    return
                prefix = "/api/bills/"
                if not parsed.path.startswith(prefix):
                    self.send_json(404, {"error": "not found"})
                    return
                payment_id = unquote(parsed.path[len(prefix):])
                state.record_request({"method": "GET", "path": parsed.path, "headers": dict(self.headers)})
                try:
                    if self.perform_action(state.take_bill_action(payment_id)):
                        return
                    self.send_json(200, state.bills_by_payment.get(payment_id, []))
                except (BrokenPipeError, ConnectionResetError):
                    # Expected when the client times out during a simulated delay.
                    return

            def do_POST(self) -> None:
                if urlparse(self.path).path != "/api/ledger/entries":
                    self.send_json(404, {"error": "not found"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.send_json(400, {"error": "invalid JSON"})
                    return
                state.record_request({"method": "POST", "path": self.path, "headers": dict(self.headers)})
                try:
                    if self.perform_action(state.take_action(state.ledger_actions)):
                        return
                    state.record_ledger_entry(payload)
                    body = b"true"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    return

        return Handler


def load_state(path: Optional[str]) -> MockPolyhedronState:
    if not path:
        return MockPolyhedronState()
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    return MockPolyhedronState(
        bills_by_payment=config.get("bills_by_payment"),
        bill_actions=config.get("bill_actions"),
        ledger_actions=config.get("ledger_actions"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local Polyhedron-compatible mock API")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (defaults to loopback)")
    parser.add_argument("--port", type=int, default=8089, help="HTTP port")
    parser.add_argument("--config", help="JSON fixture configuration")
    args = parser.parse_args()
    server = MockPolyhedronServer(load_state(args.config), args.host, args.port)
    print("Mock Polyhedron API listening at {}".format(server.base_url), flush=True)
    try:
        server.start()
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


if __name__ == "__main__":
    main()