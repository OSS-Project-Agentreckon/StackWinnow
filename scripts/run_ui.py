"""Start the checkout's local workbench and stop both child processes on exit."""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if sys.version_info < (3, 11):  # noqa: UP036 - launcher may use the system Python.
        parser.error("Use Python 3.11 or newer.")
    if any(importlib.util.find_spec(name) is None for name in ("fastapi", "uvicorn")):
        parser.error("Install the UI dependencies first: python -m pip install -e '.[ui]'")
    npm = shutil.which("npm")
    if not npm or not (root / "ui/frontend/node_modules/vite").is_dir():
        parser.error("Install Node/npm and run: npm --prefix ui/frontend ci")
    for port in (8000, 5173):
        for host in ("127.0.0.1", "::1"):
            try:
                with socket.create_connection((host, port), timeout=0.2):
                    parser.error(
                        f"Port {port} is already in use. Stop that local server before starting another."
                    )
            except OSError:
                pass
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src") + os.pathsep + environment.get("PYTHONPATH", "")
    children = []
    try:
        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "ui.api:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                    "--reload",
                ],
                cwd=root,
                env=environment,
            )
        )
        children.append(
            subprocess.Popen(
                [npm, "run", "dev", "--", "--host", "127.0.0.1", "--strictPort"],
                cwd=root / "ui/frontend",
                env=environment,
            )
        )
        print("Open http://localhost:5173 — Ctrl+C stops both servers.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.25)
        exited = next((child for child in children if child.returncode is not None), None)
        return exited.returncode if exited is not None else 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
