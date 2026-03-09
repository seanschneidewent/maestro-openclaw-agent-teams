"""Fleet CLI surface with explicit product command and staged runtime delegation."""

from __future__ import annotations

import argparse
import importlib
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import provisioning as fleet_provisioning
from . import doctor as fleet_doctor
from . import state as fleet_state
from . import update as fleet_update
from .openclaw_runtime import (
    DEFAULT_FLEET_OPENCLAW_PROFILE,
    ensure_openclaw_profile_env,
    maybe_reexec_without_disabled_malloc_stack_logging,
)


def _ensure_runtime_modules_on_path() -> None:
    try:
        import maestro  # noqa: F401
        return
    except ModuleNotFoundError:
        # Editable installs in this monorepo may not include root package deps.
        repo_root = Path(__file__).resolve().parents[4]
        legacy_pkg = repo_root / "maestro"
        if legacy_pkg.exists():
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            return
    raise SystemExit(
        "maestro-fleet depends on Fleet runtime modules currently hosted in the root package.\n"
        "Install root package too: pip install -e /absolute/path/to/repo"
    )


def _import_legacy_main() -> Callable[[list[str] | None], None]:
    _ensure_runtime_modules_on_path()
    from maestro.cli import main as legacy_main

    return legacy_main


def _load_legacy_attr(module_name: str, attr: str):
    _ensure_runtime_modules_on_path()
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _open_url(url: str) -> None:
    try:
        system = platform.system().lower()
        if system == "darwin":
            subprocess.run(["open", url], check=False)
        elif system == "windows":
            subprocess.run(["cmd", "/c", "start", "", url], check=False)
        else:
            subprocess.run(["xdg-open", url], check=False)
    except Exception:
        pass


def _run_fleet_up_tui(args: argparse.Namespace) -> int:
    from .monitor import run_up_tui

    resolved_store = str(fleet_state.resolve_fleet_store_root(args.store))
    if not args.skip_doctor:
        doctor_code = fleet_doctor.run_doctor(
            fix=not args.no_fix,
            store_override=resolved_store,
            restart_gateway=not args.no_restart,
            json_output=False,
            field_access_required=False,
        )
        if doctor_code != 0:
            return doctor_code

    run_up_tui(
        port=int(args.port),
        store=resolved_store,
        host=str(args.host),
    )
    return 0


def _run_fleet_serve(args: argparse.Namespace) -> int:
    from .server import main as server_main

    argv = ["--port", str(int(args.port)), "--host", str(args.host)]
    if getattr(args, "store", None):
        argv.extend(["--store", str(args.store)])
    return int(server_main(argv) or 0)


def _run_fleet_up(args: argparse.Namespace) -> int:
    if bool(getattr(args, "tui", False)):
        return _run_fleet_up_tui(args)

    resolved_store = str(fleet_state.resolve_fleet_store_root(args.store))
    if not args.skip_doctor:
        doctor_code = fleet_doctor.run_doctor(
            fix=not args.no_fix,
            store_override=resolved_store,
            restart_gateway=not args.no_restart,
            json_output=False,
            field_access_required=False,
        )
        if doctor_code != 0:
            return doctor_code

    args.store = resolved_store
    return _run_fleet_serve(args)


def _run_fleet_doctor(args: argparse.Namespace) -> int:
    return fleet_doctor.run_doctor(
        fix=bool(args.fix),
        store_override=args.store,
        restart_gateway=not args.no_restart,
        runtime_checks=not bool(getattr(args, "no_runtime_checks", False)),
        json_output=bool(args.json),
        field_access_required=bool(getattr(args, "field_access_required", False)),
    )


def _run_fleet_project_create(args: argparse.Namespace) -> int:
    return fleet_provisioning.run_project_create(
        project_name=args.project_name,
        assignee=args.assignee,
        superintendent=args.superintendent,
        model=args.model,
        api_key=args.api_key,
        telegram_token=args.telegram_token,
        pairing_code=args.pairing_code,
        store_override=args.store,
        dry_run=bool(args.dry_run),
        json_output=bool(args.json),
        non_interactive=bool(args.non_interactive),
        skip_remote_validation=bool(args.skip_remote_validation),
        allow_openclaw_override=bool(args.allow_openclaw_override),
    )


def _run_fleet_update(args: argparse.Namespace) -> int:
    return fleet_update.run_update(
        workspace_override=args.workspace,
        restart_gateway=not args.no_restart,
        dry_run=bool(args.dry_run),
    )


def _run_fleet_enable(args: argparse.Namespace) -> int:
    resolve_network_urls = _load_legacy_attr("maestro.control_plane", "resolve_network_urls")
    set_profile = _load_legacy_attr("maestro.profile", "set_profile")

    if args.dry_run:
        print("Fleet enable dry-run")
        print("- Would set profile=fleet and fleet_enabled=true")
        print("- Would run `maestro update` then `maestro doctor --fix`")
        return 0

    state = set_profile("fleet", fleet=True)
    print("Fleet profile enabled")
    print(f"- Profile: {state.get('profile')}")
    print(f"- Fleet enabled: {state.get('fleet_enabled')}")
    update_code = fleet_update.run_update(restart_gateway=not args.no_restart, dry_run=False)
    if update_code != 0:
        return int(update_code)
    doctor_code = fleet_doctor.run_doctor(fix=True, restart_gateway=not args.no_restart, json_output=False)
    if doctor_code != 0:
        return int(doctor_code)
    network = resolve_network_urls(web_port=3000)
    print(f"- Command Center: {network.get('recommended_url')}")
    return 0


def _run_fleet_status(_args: argparse.Namespace) -> int:
    resolve_network_urls = _load_legacy_attr("maestro.control_plane", "resolve_network_urls")
    get_profile_state = _load_legacy_attr("maestro.profile", "get_profile_state")

    state = get_profile_state()
    network = resolve_network_urls(web_port=3000)
    print("Maestro profile status")
    print(f"- profile: {state.get('profile')}")
    print(f"- fleet_enabled: {state.get('fleet_enabled')}")
    print(f"- workspace_root: {state.get('workspace_root', '')}")
    print(f"- store_root: {state.get('store_root') or state.get('fleet_store_root') or ''}")
    print(f"- command_center_url: {network.get('recommended_url')}")
    return 0


def _run_fleet_command_center(args: argparse.Namespace) -> int:
    resolve_network_urls = _load_legacy_attr("maestro.control_plane", "resolve_network_urls")
    fleet_enabled = _load_legacy_attr("maestro.profile", "fleet_enabled")

    if not fleet_enabled():
        print("Fleet mode is not enabled.")
        print("Run: maestro fleet enable")
        return 0
    network = resolve_network_urls(web_port=3000)
    url = str(network.get("recommended_url", "http://localhost:3000/command-center"))
    print(url)
    if getattr(args, "open", False):
        _open_url(url)
    return 0


def _run_fleet_deploy(args: argparse.Namespace) -> int:
    run_deploy = _load_legacy_attr("maestro.fleet_deploy", "run_deploy")
    return int(
        run_deploy(
            company_name=args.company_name,
            model=args.model,
            commander_model=args.commander_model,
            project_model=args.project_model,
            api_key=args.api_key,
            gemini_api_key=args.gemini_api_key,
            openai_api_key=args.openai_api_key,
            anthropic_api_key=args.anthropic_api_key,
            telegram_token=args.telegram_token,
            commander_pairing_code=args.commander_pairing_code,
            project_name=args.project_name,
            assignee=args.assignee,
            superintendent=args.superintendent,
            project_telegram_token=args.project_telegram_token,
            provision_initial_project=bool(args.provision_initial_project),
            store_override=args.store,
            port=int(args.port),
            host=str(args.host),
            non_interactive=bool(args.non_interactive),
            skip_remote_validation=bool(args.skip_remote_validation),
            require_tailscale=bool(args.require_tailscale),
            allow_openclaw_override=bool(args.allow_openclaw_override),
            start_services=not bool(args.no_start),
        )
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

    project = subparsers.add_parser("project", help="Project Maestro lifecycle")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_create = project_sub.add_parser("create", help="Create and provision a Project Maestro")
    project_create.add_argument("--project-name")
    project_create.add_argument("--assignee")
    project_create.add_argument("--superintendent")
    project_create.add_argument("--model")
    project_create.add_argument("--api-key")
    project_create.add_argument("--telegram-token")
    project_create.add_argument("--pairing-code")
    project_create.add_argument(
        "--maestro-license-key",
        "--project-license-key",
        dest="maestro_license_key",
        help=argparse.SUPPRESS,
    )
    project_create.add_argument("--store")
    project_create.add_argument("--dry-run", action="store_true")
    project_create.add_argument("--json", action="store_true")
    project_create.add_argument("--non-interactive", action="store_true")
    project_create.add_argument("--skip-remote-validation", action="store_true")
    project_create.add_argument("--local", "--offline", dest="local_license_mode", action="store_true")
    project_create.add_argument("--allow-openclaw-override", action="store_true")
    project_set_model = project_sub.add_parser("set-model", help="Set model for an existing Project Maestro")
    project_set_model.add_argument("--project", required=True, help="Project slug or project name")
    project_set_model.add_argument("--model", required=True)
    project_set_model.add_argument("--api-key")
    project_set_model.add_argument("--skip-remote-validation", action="store_true")
    project_set_model.add_argument("--allow-openclaw-override", action="store_true")
    project_set_model.add_argument("--store")
    project_set_telegram = project_sub.add_parser("set-telegram", help="Set Telegram bot for an existing Project Maestro")
    project_set_telegram.add_argument("--project", required=True, help="Project slug or project name")
    project_set_telegram.add_argument("--telegram-token", required=True, help="Telegram bot token to bind to the project agent")
    project_set_telegram.add_argument("--pairing-code")
    project_set_telegram.add_argument("--store")
    project_set_telegram.add_argument("--skip-remote-validation", action="store_true")
    project_set_telegram.add_argument("--allow-openclaw-override", action="store_true")

    # Legacy command kept only to return an explicit disable message from runtime.
    purchase = subparsers.add_parser("purchase", help=argparse.SUPPRESS)
    purchase.add_argument("--project-name")
    purchase.add_argument("--assignee")
    purchase.add_argument("--superintendent")
    purchase.add_argument("--model")
    purchase.add_argument("--api-key")
    purchase.add_argument("--telegram-token")
    purchase.add_argument("--pairing-code")
    purchase.add_argument("--maestro-license-key", "--project-license-key", dest="maestro_license_key", help=argparse.SUPPRESS)
    purchase.add_argument("--store")
    purchase.add_argument("--dry-run", action="store_true")
    purchase.add_argument("--json", action="store_true")
    purchase.add_argument("--non-interactive", action="store_true")
    purchase.add_argument("--skip-remote-validation", action="store_true")
    purchase.add_argument("--local", "--offline", dest="local_license_mode", action="store_true")
    purchase.add_argument("--allow-openclaw-override", action="store_true")

    license_cmd = subparsers.add_parser("license", help="Fleet local license operations")
    license_sub = license_cmd.add_subparsers(dest="license_command", required=True)
    license_generate = license_sub.add_parser("generate", help="Generate a 1-year local Fleet project key")
    license_generate.add_argument("--project-name", required=True)
    license_generate.add_argument("--project-slug")
    license_generate.add_argument("--store")
    license_generate.add_argument("--company-id")
    license_generate.add_argument("--project-id")
    license_generate.add_argument("--expiry-days", type=int, default=365)
    license_generate.add_argument("--json", action="store_true")

    deploy = subparsers.add_parser("deploy", help="One-session Fleet remote deployment workflow")
    deploy.add_argument("--company-name")
    deploy.add_argument("--model")
    deploy.add_argument("--commander-model")
    deploy.add_argument("--project-model")
    deploy.add_argument("--api-key")
    deploy.add_argument("--gemini-api-key")
    deploy.add_argument("--openai-api-key")
    deploy.add_argument("--anthropic-api-key")
    deploy.add_argument("--telegram-token")
    deploy.add_argument("--commander-pairing-code")
    deploy.add_argument("--project-name")
    deploy.add_argument("--assignee")
    deploy.add_argument("--superintendent")
    deploy.add_argument("--project-telegram-token")
    deploy.add_argument(
        "--provision-initial-project",
        action="store_true",
        help="Explicitly provision an initial project maestro during deploy",
    )
    deploy.add_argument("--store")
    deploy.add_argument("--port", type=int, default=3000)
    deploy.add_argument("--host", type=str, default="0.0.0.0")
    deploy.add_argument("--non-interactive", action="store_true")
    deploy.add_argument("--skip-remote-validation", action="store_true")
    deploy.add_argument("--local", "--offline", dest="local_license_mode", action="store_true")
    deploy.add_argument("--require-tailscale", action="store_true")
    deploy.add_argument("--allow-openclaw-override", action="store_true")
    deploy.add_argument("--no-start", action="store_true")

    commander = subparsers.add_parser("commander", help="Commander lifecycle operations")
    commander_sub = commander.add_subparsers(dest="commander_command", required=True)
    commander_set_model = commander_sub.add_parser("set-model", help="Set commander model")
    commander_set_model.add_argument("--model", required=True)
    commander_set_model.add_argument("--api-key")
    commander_set_model.add_argument("--skip-remote-validation", action="store_true")
    commander_set_model.add_argument("--allow-openclaw-override", action="store_true")
    commander_set_model.add_argument("--store")

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
    doctor.add_argument("--no-runtime-checks", action="store_true", help=argparse.SUPPRESS)
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
    if command in {"enable", "status", "purchase", "deploy", "command-center"}:
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
                    "local_license_mode": "--local",
                    "allow_openclaw_override": "--allow-openclaw-override",
                },
            )
        if command == "deploy":
            return base + _flag_args(
                args,
                {
                    "company_name": "--company-name",
                    "model": "--model",
                    "commander_model": "--commander-model",
                    "project_model": "--project-model",
                    "api_key": "--api-key",
                    "gemini_api_key": "--gemini-api-key",
                    "openai_api_key": "--openai-api-key",
                    "anthropic_api_key": "--anthropic-api-key",
                    "telegram_token": "--telegram-token",
                    "commander_pairing_code": "--commander-pairing-code",
                    "project_name": "--project-name",
                    "assignee": "--assignee",
                    "superintendent": "--superintendent",
                    "project_telegram_token": "--project-telegram-token",
                    "provision_initial_project": "--provision-initial-project",
                    "store": "--store",
                    "port": "--port",
                    "host": "--host",
                    "non_interactive": "--non-interactive",
                    "skip_remote_validation": "--skip-remote-validation",
                    "local_license_mode": "--local",
                    "require_tailscale": "--require-tailscale",
                    "allow_openclaw_override": "--allow-openclaw-override",
                    "no_start": "--no-start",
                },
            )
        if command == "command-center":
            return base + _flag_args(args, {"open": "--open"})
        return base
    if command == "project":
        sub = str(getattr(args, "project_command", "")).strip()
        if sub == "create":
            return ["fleet", "project", "create"] + _flag_args(
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
                    "local_license_mode": "--local",
                    "allow_openclaw_override": "--allow-openclaw-override",
                },
            )
        if sub == "set-model":
            return ["fleet", "project", "set-model"] + _flag_args(
                args,
                {
                    "project": "--project",
                    "model": "--model",
                    "api_key": "--api-key",
                    "skip_remote_validation": "--skip-remote-validation",
                    "allow_openclaw_override": "--allow-openclaw-override",
                    "store": "--store",
                },
            )
        if sub == "set-telegram":
            return ["fleet", "project", "set-telegram"] + _flag_args(
                args,
                {
                    "project": "--project",
                    "telegram_token": "--telegram-token",
                    "pairing_code": "--pairing-code",
                    "skip_remote_validation": "--skip-remote-validation",
                    "allow_openclaw_override": "--allow-openclaw-override",
                    "store": "--store",
                },
            )
        raise SystemExit(f"Unknown project command: {sub}")
    if command == "commander":
        sub = str(getattr(args, "commander_command", "")).strip()
        if sub == "set-model":
            return ["fleet", "commander", "set-model"] + _flag_args(
                args,
                {
                    "model": "--model",
                    "api_key": "--api-key",
                    "skip_remote_validation": "--skip-remote-validation",
                    "allow_openclaw_override": "--allow-openclaw-override",
                    "store": "--store",
                },
            )
        raise SystemExit(f"Unknown commander command: {sub}")
    if command == "license":
        sub = str(getattr(args, "license_command", "")).strip()
        if sub == "generate":
            return ["fleet", "license", "generate"] + _flag_args(
                args,
                {
                    "project_name": "--project-name",
                    "project_slug": "--project-slug",
                    "store": "--store",
                    "company_id": "--company-id",
                    "project_id": "--project-id",
                    "expiry_days": "--expiry-days",
                    "json": "--json",
                },
            )
        raise SystemExit(f"Unknown license command: {sub}")

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
            {
                "fix": "--fix",
                "store": "--store",
                "no_restart": "--no-restart",
                "no_runtime_checks": "--no-runtime-checks",
                "json": "--json",
            },
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
    if argv is None:
        maybe_reexec_without_disabled_malloc_stack_logging(module="maestro_fleet")

    ensure_openclaw_profile_env(default_profile=DEFAULT_FLEET_OPENCLAW_PROFILE)

    parser = build_parser()
    args = parser.parse_args(argv)

    command = str(args.command).strip()
    if command == "up":
        print("[fleet] launching package-native Fleet runtime")
        try:
            return _run_fleet_up(args)
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return 0
            if isinstance(code, int):
                return code
            print(str(code), file=sys.stderr)
            return 1
    if command == "serve":
        print("[fleet] launching package-native Fleet server")
        return _run_fleet_serve(args)
    if command == "doctor":
        print("[fleet] running package-native Fleet doctor")
        return _run_fleet_doctor(args)
    if command == "update":
        print("[fleet] running package-native Fleet update")
        return _run_fleet_update(args)
    if command == "enable":
        print("[fleet] enabling Fleet profile")
        return _run_fleet_enable(args)
    if command == "status":
        print("[fleet] reading Fleet profile status")
        return _run_fleet_status(args)
    if command == "command-center":
        print("[fleet] resolving Fleet command center")
        return _run_fleet_command_center(args)
    if command == "deploy":
        print("[fleet] running Fleet deploy")
        return _run_fleet_deploy(args)
    if command == "project" and str(getattr(args, "project_command", "")).strip() == "create":
        print("[fleet] running package-native project create")
        return _run_fleet_project_create(args)

    print("[fleet] forwarding compatibility command")
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
