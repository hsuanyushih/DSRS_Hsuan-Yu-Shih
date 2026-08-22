"""Local web UI -- type a question in the browser, calls agents.answer.main() to show the reply.

Just a convenience shell for manual testing, not part of the Chapter 4 contract:
agents/answer.py is untouched, this only imports and calls its main(). Uses only the
standard library (http.server), no extra packages required.

Run:
    python3 -m webui.server
then open http://localhost:8765
"""

from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import answer  # noqa: E402

PORT = 8765
INDEX_HTML = (Path(__file__).resolve().parent / "index.html").read_bytes()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # keep quiet, don't spam the terminal
        pass

    def do_GET(self) -> None:
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(INDEX_HTML)))
        self.end_headers()
        self.wfile.write(INDEX_HTML)

    def do_POST(self) -> None:
        if self.path != "/ask":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            question = json.loads(body)["question"].strip()
            if not question:
                raise ValueError("empty question")
            result = answer.main(question)
        except Exception as exc:  # noqa: BLE001 -- the frontend should see the error message, not a blank 500
            traceback.print_exc()
            result = {"error": str(exc)}

        payload = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    print(f"open http://localhost:{PORT}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
