#!/usr/bin/env python3
"""Import a simulator trace into a running MindStudio Insight instance via its
WebSocket API, without touching the browser UI.

Usage:
  insight-import.py <path-to-visualize_data.bin-or-trace-dir> [--project NAME] [--port 9880] [--host 127.0.0.1]

The <path> may be the visualize_data.bin file itself, or a directory containing
it (the simulator/ output dir). Host paths under this repo's out/ tree are
mapped to the container's /opt/insight/data mount automatically.

Caveat: profiler_server accepts a SINGLE client connection. If the Insight
browser tab is open, it holds the connection and a second connection is
rejected ("server is already connected"). Close the browser tab first (or run
a second dedicated Insight container on another port).
"""
import argparse
import glob
import json
import os
import sys
import time

import websocket  # websocket-client


def find_bin(path):
    if path.endswith(".bin"):
        return path  # direct .bin file (host or container path)
    if os.path.isdir(path):
        hits = glob.glob(os.path.join(path, "**", "visualize_data.bin"), recursive=True)
        if hits:
            return hits[0]
    raise SystemExit(f"visualize_data.bin not found under: {path}")


def to_container_path(host_path):
    """Map a host path under <repo>/out to /opt/insight/data; pass container
    paths (/opt/insight/...) through unchanged."""
    host_path = os.path.abspath(host_path)
    if host_path.startswith("/opt/insight/"):
        return host_path
    parts = host_path.split(os.sep)
    if "out" in parts:
        idx = parts.index("out")
        return os.path.join("/opt/insight/data", *parts[idx + 1:])
    raise SystemExit(
        f"cannot map path to container: {host_path}\n"
        "(pass a path under out/, or a full /opt/insight/data/... container path)"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="visualize_data.bin file, or a directory containing it")
    ap.add_argument("--project", default=None, help="project name (default: trace dir basename)")
    ap.add_argument("--port", default=9880, type=int, help="Insight port (default 9880)")
    ap.add_argument("--host", default="127.0.0.1", help="Insight host (default 127.0.0.1)")
    args = ap.parse_args()

    bin_path = find_bin(args.path)
    con_path = to_container_path(bin_path)
    project = args.project or os.path.basename(os.path.dirname(os.path.dirname(bin_path)))
    # strip the OPPROF timestamp dir: use the parent-of-parent-of-parent if it looks like a trace name
    if args.project is None:
        d = os.path.dirname(bin_path)  # .../simulator
        d = os.path.dirname(d)          # .../OPPROF_<ts>_<id>
        d = os.path.dirname(d)          # .../cube_peak-64x64x64-half-<ts>
        project = os.path.basename(d)

    url = f"ws://{args.host}:{args.port}/proxy/9000"
    print(f"importing {con_path} as project '{project}'")
    try:
        ws = websocket.create_connection(url, timeout=15)
    except Exception as e:
        raise SystemExit(f"connect failed: {e}\n(hint: close the Insight browser tab; only one client is allowed)")

    msg = {
        "id": int(time.time() * 1000) % (2**31),
        "moduleName": "timeline",
        "type": "request",
        "command": "import/action",
        "projectName": project,
        "params": {
            "projectName": project,
            "path": [con_path],
            "projectAction": 1,  # ADD_FILE
            "isConflict": False,
        },
    }
    ws.send(json.dumps(msg))

    result = None
    success = False
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            raw = ws.recv()
        except Exception:
            break
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if m.get("command") == "import/action" and m.get("type") == "response":
            result = m
            if m.get("result") is True:
                success = True
            else:
                print("import failed:", json.dumps(m.get("error", {}), ensure_ascii=False))
                break
        elif m.get("event") == "parse/success":
            print("parse success")
            success = True
            break
        elif m.get("event") == "parse/fail":
            print("parse fail:", json.dumps(m.get("body", {}), ensure_ascii=False))
            break
    ws.close()

    if result is None and not success:
        raise SystemExit("no import response received")
    if not success:
        raise SystemExit("import did not complete successfully")
    print(f"OK: imported '{project}' ({bin_path})")


if __name__ == "__main__":
    main()
