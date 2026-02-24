"""Fleet CLI surface with explicit product command and staged runtime delegation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable


def _import_legacy_main() -> Callable[[list[str] | None], None]:
    try:
        from maestro.cli import main as legacy_main

        return legacy_main
    except ModuleNotFoundError:
        # Editable installs in this monorepo may not include root package deps.
        repo_root = Path(__file__).resolve().parents[4]
        legacy_pkg = repo_root / "maestro"
        if legacy_pkg.exists():
            sys.path.insert(0, str(repo_root))
            from maestro.cli import main as legacy_main  # type: ignore

            return legacy_main
    raise SystemExit(
        "maestro-fleet depends on Fleet runtime modules currently hosted in the root package.\n"
        "Install root package too: pip install -e /absolute/path/to/repo"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maestro-fleet",
        description="Maestro Fleet — enterprise command surface",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    enable = subparsers.add_parser("enable", help="Enable Fleet profile + command center")
    enable.add_argument("--no-restart", action="store_true", help="Skip gateway restart flows")
    enable.add_argument("--dry-run", action="store_true", help="Show actions without changing profile")

    subparsers.add_parser("status", help="Show Fleet profile/capability status")

    purchase = subparsers.add_parser("purchase", help="Provision a project-specific Maestro")
    purchase.add_argument("--project-name")
    purchase.add_argument("--assignee")
    purchase.add_argument("--superintendent")
    purchase.add_argument("--model")
    purchase.add_argument("--api-key")
    purchase.add_argument("--telegram-token")
    purchase.add_argument("--pairing-code")
    purchase.add_argument(
        "--maestro-license-key",
        "--project-license-key",
        dest="maestro_license_key",
        help=argparse.SUPPRESS,
    )
    purchase.add_argument("--store")
    purchase.add_argument("--dry-run", action="store_true")
    purchase.add_argument("--json", action="store_true")
    purchase.add_argument("--non-interactive", action="store_true")
    purchase.add_argument("--skip-remote-validation", action="store_true")

    cc = subparsers.add_parser("command-center", help="Show/open command center URL")
    cc.add_argument("--open", action="store_true", help="Open URL in browser")

    ingest = subparsers.add_parser("ingest", help="Ingest PDFs into Fleet store")
    ingest.add_argument("folder", help="Path to folder containing PDFs")
    ingest.add_argument("--project-name", "-n", help="Project name")
    ingest.add_argument("--dpi", type=int, default=200, help="Render DPI (default: 200)")
    ingest.add_argument("--store", help="Override knowledge store path")

    serve = subparsers.add_parser("serve", help="Start Fleet server")
    serve.add_argument("--port", type=int, default=3000)
    serve.add_argument("--store", type=str, default=None, help="Override fleet store root")
    serve.add_argument("--host", type=str, default="0.0.0.0")

    doctor = subparsers.add_parser("doctor", help="Validate and repair Fleet runtime setup")
    doctor.add_argument("--fix", action="store_true", help="Apply safe fixes in-place")
    doctor.add_argument("--store", help="Override knowledge store path used in checks")
    doctor.add_argument("--no-restart", action="store_true", help="Skip gateway restart checks")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON output")

    up = subparsers.add_parser("up", help="Preferred Fleet startup: doctor --fix then serve")
    up.add_argument("--port", type=int, default=3000)
    up.add_argument("--store", type=str, default=None, help="Override fleet store root")
    up.add_argument("--host", type=str, default="0.0.0.0")
    up.add_argument("--tui", action="store_true", help="Run server with live monitor TUI")
    up.add_argument("--skip-doctor", action="store_true", help="Skip doctor pass before serving")
    up.add_argument("--no-fix", action="store_true", help="Run doctor in validate-only mode")
    up.add_argument("--no-restart", action="store_true", help="Skip gateway restart during doctor pass")

    update = subparsers.add_parser("update", help="Update existing Fleet install")
    update.add_argument("--workspace", help="Override workspace path for maestro-company")
    update.add_argument("--no-restart", action="store_true", help="Skip OpenClaw gateway restart/start")
    update.add_argument("--dry-run", action="store_true", help="Show planned changes without writing files")

    return parser


def _flag_args(args: argparse.Namespace, mapping: dict[str, str]) -> list[str]:
    forwarded: list[str] = []
    for attr, flag in mapping.items():
        value = getattr(args, attr, None)
        if isinstance(value, bool):
            if value:
                forwarded.append(flag)
            continue
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        forwarded.extend([flag, text])
    return forwarded


def _to_legacy_argv(args: argparse.Namespace) -> list[str]:
    command = str(args.command).strip()
    if command in {"enable", "status", "purchase", "command-center"}:
        base = ["fleet", command]
        if command == "enable":
            return base + _flag_args(args, {"no_restart": "--no-restart", "dry_run": "--dry-run"})
        if command == "purchase":
            return base + _flag_args(
                args,
                {
                    "project_name": "--project-name",
                    "assignee": "--assignee",
                    "superintendent": "--superintendent",
                    "model": "--model",
                    "api_key": "--api-key",
                    "telegram_token": "--telegram-token",
                    "pairing_code": "--pairing-code",
                    "maestro_license_key": "--maestro-license-key",
                    "store": "--store",
                    "dry_run": "--dry-run",
                    "json": "--json",
                    "non_interactive": "--non-interactive",
                    "skip_remote_validation": "--skip-remote-validation",
                },
            )
        if command == "command-center":
            return base + _flag_args(args, {"open": "--open"})
        return base

    if command == "ingest":
        return ["ingest", str(args.folder)] + _flag_args(
            args,
            {"project_name": "--project-name", "dpi": "--dpi", "store": "--store"},
        )
    if command == "serve":
        return ["serve"] + _flag_args(args, {"port": "--port", "store": "--store", "host": "--host"})
    if command == "doctor":
        return ["doctor"] + _flag_args(
            args,
            {"fix": "--fix", "store": "--store", "no_restart": "--no-restart", "json": "--json"},
        )
    if command == "up":
        return ["up"] + _flag_args(
            args,
            {
                "port": "--port",
                "store": "--store",
                "host": "--host",
                "tui": "--tui",
                "skip_doctor": "--skip-doctor",
                "no_fix": "--no-fix",
                "no_restart": "--no-restart",
            },
        )
    if command == "update":
        return ["update"] + _flag_args(
            args,
            {"workspace": "--workspace", "no_restart": "--no-restart", "dry_run": "--dry-run"},
        )
    raise SystemExit(f"Unknown command: {command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    print("[fleet-staging] maestro-fleet delegates to current Fleet runtime modules in `maestro/`.")
    legacy_main = _import_legacy_main()
    forwarded = _to_legacy_argv(args)
    try:
        legacy_main(forwarded)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(str(code), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
