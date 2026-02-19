#!/usr/bin/env python3
"""
Maestro Knowledge Tools — CLI wrapper for OpenClaw agent integration.

This is a thin shim that delegates to the maestro package.
The canonical implementation lives in maestro/tools.py and maestro/cli.py.

Usage:
    python tools.py <command> [args]
"""

import os
import sys
from pathlib import Path

# Add package root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent.parent.parent.parent  # agent/skills/maestro/scripts/ → repo root
sys.path.insert(0, str(PACKAGE_ROOT))

# Set MAESTRO_STORE if not already set
WORKSPACE = Path(os.environ.get("MAESTRO_WORKSPACE", SCRIPT_DIR.parent.parent.parent))
if not os.environ.get("MAESTRO_STORE"):
    os.environ["MAESTRO_STORE"] = str(WORKSPACE / "knowledge_store")

# Delegate to the package CLI
from maestro.cli import _run_tools
import argparse

if __name__ == "__main__":
    # Re-invoke as "maestro tools <args>"
    sys.argv = ["maestro", "tools"] + sys.argv[1:]
    from maestro.cli import main
    main()
