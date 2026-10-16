#!/usr/bin/env python3
"""Start Vinted Finder on this computer, optionally with a free public link.

    python3 start.py           # http://localhost:8000 (just you)
    python3 start.py --share   # also prints a public https://....trycloudflare.com link

Works on macOS, Linux and Windows. First run creates .venv and installs
dependencies; --share downloads Cloudflare's free `cloudflared` tunnel tool
(no account needed). Put ANTHROPIC_API_KEY in a .env file for Claude ranking.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
BIN = VENV / ("Scripts" if os.name == "nt" else "bin")
PY = BIN / ("python.exe" if os.name == "nt" else "python")
TOOLS = ROOT / ".tools"
RELEASES = "https://github.com/cloudflare/cloudflared/releases/latest/download/"


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value and key.strip() not in os.environ:
                os.environ[key.strip()] = value


def install():
    if not PY.exists():
        print("Creating virtual environment...")
        venv.create(VENV, with_pip=True)
    stamp = VENV / ".installed"
    req = ROOT / "requirements.txt"
    if not stamp.exists() or req.stat().st_mtime > stamp.stat().st_mtime:
        print("Installing dependencies (first run takes a couple of minutes)...")
        subprocess.check_call([str(PY), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        subprocess.check_call([str(PY), "-m", "pip", "install", "-q", "-r", str(req)])
        stamp.touch()


def cloudflared() -> str:
    if found := shutil.which("cloudflared"):
        return found
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    TOOLS.mkdir(exist_ok=True)
    exe = TOOLS / ("cloudflared.exe" if system == "windows" else "cloudflared")
    if exe.exists():
        return str(exe)
    print("Downloading cloudflared (free Cloudflare tunnel)...")
    if system == "windows":
        urllib.request.urlretrieve(RELEASES + "cloudflared-windows-amd64.exe", exe)
    elif system == "darwin":
        archive = TOOLS / "cloudflared.tgz"
        urllib.request.urlretrieve(RELEASES + f"cloudflared-darwin-{arch}.tgz", archive)
        with tarfile.open(archive) as tar:
            member = next(m for m in tar.getmembers() if m.name.endswith("cloudflared"))
            member.name = exe.name
            tar.extract(member, TOOLS)
        archive.unlink()
    else:
        urllib.request.urlretrieve(RELEASES + f"cloudflared-linux-{arch}", exe)
    exe.chmod(0o755)
    return str(exe)


def wait_for_server(port: int, proc: subprocess.Popen, timeout: float = 120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            sys.exit("The server stopped unexpectedly; see the messages above.")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2)
            return
        except OSError:
            time.sleep(1)
    sys.exit("The server didn't start in time.")


def start_tunnel(port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [cloudflared(), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    state = {"url": None, "connected": False}

    def watch():
        for line in proc.stdout:
            if not state["url"]:
                if m := re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line):
                    state["url"] = m.group(0)
            # The link only works once cloudflared has a live connection.
            if state["url"] and not state["connected"] and "Registered tunnel connection" in line:
                state["connected"] = True
                bar = "=" * 64
                print(f"\n{bar}\n  Public link for testers:\n  {state['url']}\n{bar}\n", flush=True)

    def check():
        time.sleep(45)
        if not state["connected"] and proc.poll() is None:
            print(
                "\n[tunnel] Still can't reach Cloudflare. A firewall, VPN or school/work network "
                "may be blocking it (it needs outbound port 7844 or 443). The app still works "
                "locally; try another network or see the README for free hosting.\n",
                flush=True,
            )

    threading.Thread(target=watch, daemon=True).start()
    threading.Thread(target=check, daemon=True).start()
    return proc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--share", action="store_true", help="create a free public link via Cloudflare")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = ap.parse_args()

    os.chdir(ROOT)
    load_env()
    install()

    if os.environ.get("ANTHROPIC_API_KEY"):
        model = os.environ.get("VINTED_FINDER_MODEL", "claude-haiku-5-5")
        print(f"Claude ranking on ({model}); free photo matching if it's unavailable.")
    else:
        print("No ANTHROPIC_API_KEY in .env: using free photo matching.")
    print(f"Daily limit: {os.environ.get('DAILY_LIMIT', '20')} searches per visitor.")

    server = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "vinted_finder.app:app",
         "--host", "127.0.0.1", "--port", str(args.port), "--log-level", "warning"]
    )
    tunnel = None
    try:
        wait_for_server(args.port, server)
        print(f"Running at http://localhost:{args.port}  (Ctrl+C to stop)")
        if args.share:
            print("Opening a public tunnel...")
            tunnel = start_tunnel(args.port)
        server.wait()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for p in (tunnel, server):
            if p and p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
