"""
rayflux_studio.py
One-click Python launcher for RayFlux Studio (Local Operations, Multi-Area GIS,
CV Profile Builder, Data Manager, PostGIS Health & Pipeline Runner).

Usage:
  .venv/Scripts/python.exe rayflux_studio.py
  .venv/Scripts/python.exe rayflux_studio.py --port 8765 --no-browser
"""
import argparse
from pathlib import Path
import sys
import threading
import time
import webbrowser

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

import uvicorn
from studio.smart_logger import studio_logger


def _open_browser_later(url: str) -> None:
    time.sleep(1.3)
    webbrowser.open(url)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch RayFlux Studio Control Center")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser window")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print("=" * 72)
    print("  RAYFLUX STUDIO — SOLAR INTELLIGENCE CONTROL CENTER")
    print(f"  Listening on : {url}")
    print("  Press CTRL+C to stop.")
    print("=" * 72)

    studio_logger.info(f"RayFlux Studio started on {url}.", section="STUDIO")
    if not args.no_browser:
        threading.Thread(target=_open_browser_later, args=(url,), daemon=True).start()

    uvicorn.run("studio.server:app", host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
