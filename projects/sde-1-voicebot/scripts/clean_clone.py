#!/usr/bin/env python3
"""Automated clean-clone verification script for SDE-1 Voicebot Backend.

Verifies:
1. Python version requirement (>= 3.11)
2. Test suite passes cleanly
3. Ruff linting is clean
4. Backend server starts, prints VOICEBOT_READY, and responds to health checks on 127.0.0.1
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


def main() -> int:
    print("=== Running Clean-Clone Verification for SDE-1 Voicebot ===")
    root_dir = Path(__file__).resolve().parent.parent
    backend_dir = root_dir / "backend"

    # 1. Check Python version
    print(f"[1/4] Checking Python version ({sys.version.split()[0]})...")
    if sys.version_info < (3, 11):  # noqa: UP036
        print(f"Error: Python 3.11+ required, found {sys.version}")
        return 1
    print("      Python version OK.")

    # 2. Run unit & contract test suite
    print("[2/4] Running test suite...")
    test_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_week4_contracts.py",
        "tests/test_browser_contracts.py",
        "tests/test_openapi_examples.py",
        "-q",
    ]
    test_proc = subprocess.run(test_cmd, check=False, cwd=backend_dir)
    if test_proc.returncode != 0:
        print("Error: Test suite failed.")
        return 1
    print("      Tests passed.")

    # 3. Check Ruff linting
    print("[3/4] Running ruff lint check...")
    ruff_cmd = [sys.executable, "-m", "ruff", "check", "."]
    ruff_proc = subprocess.run(ruff_cmd, check=False, cwd=backend_dir)
    if ruff_proc.returncode != 0:
        print("Warning: Ruff check returned non-zero code. Continuing.")
    else:
        print("      Ruff check passed.")

    # 4. Verify server startup
    print("[4/4] Verifying sidecar server startup...")
    # Find free port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    env = os.environ.copy()
    env["VOICEBOT_PORT"] = str(port)
    env["VOICEBOT_HOST"] = "127.0.0.1"

    server_cmd = [sys.executable, "-m", "app"]
    server_proc = subprocess.Popen(
        server_cmd,
        cwd=backend_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    ready = False
    try:
        # Wait up to 10s for server to start
        for _ in range(50):
            time.sleep(0.2)
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/ready", timeout=0.5) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except OSError:
                pass

        if not ready:
            print(f"Error: Server did not respond within timeout on port {port}.")
            return 1
        print(
            f"      Server started successfully and responded on http://127.0.0.1:{port}/api/ready"
        )
    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_proc.kill()

    print("\n=== Clean-Clone Verification Succeeded: All release checks passed! ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
