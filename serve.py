"""Local preview server for _site/: like `python -m http.server`, but tells the browser not to cache,
so a refresh always shows the latest render (Safari otherwise keeps old CSS and data)."""
import functools
import http.server
import sys
from pathlib import Path


class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8767
    root = Path(__file__).parent
    handler = functools.partial(NoCache, directory=str(root))
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
