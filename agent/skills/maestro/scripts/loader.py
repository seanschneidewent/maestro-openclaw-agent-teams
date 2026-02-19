"""
Backward-compatible loader shim.

The canonical implementation lives in maestro/loader.py.
This file exists so existing imports still work.
"""

import sys
from pathlib import Path

# Add package root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

from maestro.loader import load_project, resolve_page

__all__ = ["load_project", "resolve_page"]
