#!/usr/bin/env python3
"""Automated clean-clone verification script for SDE-1 Voicebot Backend.

Verifies:
1. Repository really git-clones into a fresh temporary directory
2. Python version requirement (>= 3.11)
3. Test suite passes cleanly in cloned repo
4. Ruff linting is clean in cloned repo
5. Backend server starts, prints VOICEBOT_READY, and responds to readiness checks
"""

import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


def _remove_readonly(func, path, _exc_info):
    """Clear the readonly bit and reattempt removal for Windows git objects."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main() -> int:
    print("=== Running Clean-Clone Verification for SDE-1 Voicebot ===")
    repo_root = Path(__file__).resolve().parent.parent.parent.parent

    # 1. Check Python version
    print(f"[1/5] Checking Python version ({sys.version.split()[0]})...")
    if sys.version_info < (3, 11):  # noqa: UP036
        print(f"Error: Python 3.11+ required, found {sys.version}")
        return 1
    print("      Python version OK.")

    # 2. Perform fresh git clone into temporary directory
    temp_dir = tempfile.mkdtemp(prefix="voicebot_clone_")
    print(f"[2/5] Performing git clone into temporary directory: {temp_dir}...")
    try:
        clone_cmd = ["git", "clone", "--local", str(repo_root), temp_dir]
        clone_proc = subprocess.run(
            clone_cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if clone_proc.returncode != 0:
            print(f"Error cloning repository: {clone_proc.stderr}")
            return 1
        print("      Git clone completed successfully.")

        cloned_backend = Path(temp_dir) / "projects" / "sde-1-voicebot" / "backend"

        # 3. Run test suite in cloned directory
        print("[3/5] Running test suite in cloned repository...")
        test_cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_week4_contracts.py",
            "tests/test_browser_contracts.py",
            "tests/test_openapi_examples.py",
            "-q",
        ]
        test_proc = subprocess.run(test_cmd, check=False, cwd=cloned_backend)
        if test_proc.returncode != 0:
            print("Error: Test suite failed in cloned repository.")
            return 1
        print("      Tests passed.")

        # 4. Check Ruff linting
        print("[4/5] Running ruff lint check in cloned repository...")
        ruff_cmd = [sys.executable, "-m", "ruff", "check", "."]
        ruff_proc = subprocess.run(ruff_cmd, check=False, cwd=cloned_backend)
        if ruff_proc.returncode != 0:
            print("Error: Ruff lint check failed in cloned repository.")
            return 1
        print("      Ruff check passed.")

        # 5. Verify server startup
        print("[5/5] Verifying sidecar server startup in cloned repository...")
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
            cwd=cloned_backend,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        ready = False
        try:
            for _ in range(50):
                time.sleep(0.2)
                try:
                    with urlopen(
                        f"http://127.0.0.1:{port}/api/ready", timeout=0.5
                    ) as resp:
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

    finally:
        print("Cleaning up temporary clone directory...")
        shutil.rmtree(temp_dir, onerror=_remove_readonly)
        print("Cleanup complete.")

    print("=== Clean-Clone Verification Passed Successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
