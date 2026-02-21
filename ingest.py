#!/usr/bin/env python3
"""Compatibility wrapper for legacy `python ingest.py` usage.

Canonical ingest implementation lives in `maestro.ingest` and should be invoked via:
    maestro ingest ...
"""

from __future__ import annotations

import argparse

from maestro.ingest import ingest


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest PDFs into Maestro knowledge store")
    parser.add_argument("folder", help="Path to folder containing PDFs")
    parser.add_argument("--project-name", "-n", help="Project name")
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI (default: 200)")
    parser.add_argument("--store", help="Override knowledge_store path")
    args = parser.parse_args()

    ingest(args.folder, args.project_name, args.dpi, args.store)


if __name__ == "__main__":
    main()
