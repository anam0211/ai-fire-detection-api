"""Start a temporary real server, run HTTP smoke tests, then stop that server."""

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-web-client", action="store_true", help="Also run the Node backend client over real HTTP")
    args = parser.parse_args()
    node = shutil.which("node") if args.check_web_client else None
    if args.check_web_client and node is None:
        raise RuntimeError("Node with built-in fetch is required for --check-web-client")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = {
        **os.environ, "API_KEY": secrets.token_urlsafe(32), "PORT": str(port),
        "DASHBOARD_ORIGINS": "http://localhost:5173", "PYTHONDONTWRITEBYTECODE": "1",
    }
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryFile() as server_log:
        server = subprocess.Popen(
            [sys.executable, str(ROOT / "api.py")], cwd=ROOT / "scripts", env=environment,
            stdout=server_log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 45
            while True:
                if server.poll() is not None:
                    raise RuntimeError("API exited during startup")
                try:
                    with urlopen(base + "/health", timeout=1) as response:
                        if response.status == 200 and json.load(response)["ok"]:
                            break
                except (URLError, TimeoutError):
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("API did not become healthy within 45 seconds")
                time.sleep(0.2)
            print(f"Real server ready at {base}; PORT from environment; cwd=scripts", flush=True)
            result = subprocess.run(
                [sys.executable, "-u", str(ROOT / "scripts" / "smoke_test.py"),
                 "--base-url", base, "--check-offline"],
                cwd=ROOT, env=environment, timeout=180, check=False,
            )
            if result.returncode != 0 or not args.check_web_client:
                return result.returncode
            web_result = subprocess.run(
                [node, str(ROOT / "web_client" / "verify.mjs")], cwd=ROOT,
                env={**environment, "AI_API_URL": base, "AI_API_KEY": environment["API_KEY"]},
                timeout=180, check=False,
            )
            return web_result.returncode
        except Exception:
            server_log.seek(0)
            print(server_log.read().decode("utf-8", errors="replace"), file=sys.stderr)
            raise
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
