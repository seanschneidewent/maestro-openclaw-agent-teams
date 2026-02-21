#!/usr/bin/env python3
"""Compatibility wrapper for legacy `python server.py` usage.

Canonical server implementation lives in `maestro.server` and should be invoked via:
    maestro serve ...
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from maestro.server import app
import maestro.server as server_module


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Maestro web server")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--store", type=str, default="knowledge_store")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    server_module.store_path = Path(args.store).resolve()
    print(f"Maestro server starting on http://localhost:{args.port}")
    print(f"Knowledge store: {server_module.store_path}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
