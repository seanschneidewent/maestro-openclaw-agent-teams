"""Helpers for shipping customer-facing Maestro help packs."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from maestro import __version__


HELP_PACK_METADATA = ".maestro-help-pack.json"


def fleet_help_pack_dir() -> Path:
    """Return the packaged Fleet help-pack asset directory."""
    return Path(__file__).resolve().parent / "customer_help" / "fleet"


def bundled_fleet_help_pdfs() -> list[Path]:
    """Return the managed PDF files bundled with the package."""
    source_dir = fleet_help_pack_dir()
    return sorted(path for path in source_dir.glob("*.pdf") if path.is_file())


def _load_existing_metadata(metadata_path: Path) -> dict[str, Any]:
    if not metadata_path.is_file():
        return {}
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def install_fleet_help_pack(target_dir: Path) -> Path:
    """Install the bundled Fleet help pack into the target directory.

    Managed PDFs are overwritten on reinstall. Files previously tracked in the
    metadata file but removed from the current bundle are cleaned up. Unknown
    user files are left alone.
    """

    source_dir = fleet_help_pack_dir()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Fleet help-pack assets not found: {source_dir}")

    source_pdfs = bundled_fleet_help_pdfs()
    if not source_pdfs:
        raise FileNotFoundError(f"No Fleet help-pack PDFs found in: {source_dir}")

    target_dir = Path(target_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = target_dir / HELP_PACK_METADATA
    existing_metadata = _load_existing_metadata(metadata_path)
    previous_managed = {
        str(name)
        for name in existing_metadata.get("managed_files", [])
        if isinstance(name, str) and name.strip()
    }
    current_managed = [path.name for path in source_pdfs]

    for stale_name in sorted(previous_managed - set(current_managed)):
        stale_path = target_dir / stale_name
        if stale_path.is_file():
            stale_path.unlink()

    for source_pdf in source_pdfs:
        shutil.copy2(source_pdf, target_dir / source_pdf.name)

    metadata = {
        "product": "maestro-fleet",
        "help_pack": "customer-desktop",
        "version": __version__,
        "installed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "managed_files": current_managed,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return target_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m maestro.help_pack")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_fleet = subparsers.add_parser(
        "install-fleet",
        help="Install the bundled Maestro Fleet desktop help pack",
    )
    install_fleet.add_argument(
        "--target-dir",
        required=True,
        help="Directory where the Maestro Fleet Help folder should be created/refreshed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "install-fleet":
            installed_dir = install_fleet_help_pack(Path(args.target_dir))
            print(installed_dir)
            return 0
    except Exception as exc:  # pragma: no cover - CLI error path
        print(str(exc), file=sys.stderr)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover - manual CLI entry
    raise SystemExit(main())
