"""
Maestro CLI — unified entry point for all Maestro commands.

Usage:
    maestro ingest <folder> [options]
    maestro serve [options]
    maestro start [options]
    maestro doctor [options]
    maestro update [options]
    maestro up [options]
    maestro tools <command> [args]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent_role import is_company_role
from .install_state import resolve_fleet_store_root


def _add_ingest_parser(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser("ingest", help="Ingest PDFs into knowledge store")
    parser.add_argument("folder", help="Path to folder containing PDFs")
    parser.add_argument("--project-name", "-n", help="Project name")
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI (default: 200)")
    parser.add_argument("--store", help="Override knowledge_store path")


def _add_start_parser(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser("start", help="Start Maestro runtime (TUI dashboard)")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--store", type=str, default=None, help="Override fleet store root")


def _add_serve_parser(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser("serve", help="Start the frontend server")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--store", type=str, default=None, help="Override fleet store root")
    parser.add_argument("--host", type=str, default="0.0.0.0")


def _add_update_parser(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser("update", help="Update an existing Maestro install")
    parser.add_argument("--workspace", help="Override workspace path for maestro-company")
    parser.add_argument("--no-restart", action="store_true", help="Skip OpenClaw gateway restart/start")
    parser.add_argument("--dry-run", action="store_true", help="Show planned changes without writing files")


def _add_doctor_parser(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser("doctor", help="Validate and repair Maestro/OpenClaw runtime setup")
    parser.add_argument("--fix", action="store_true", help="Apply safe fixes in-place")
    parser.add_argument("--store", help="Override knowledge store path used in checks")
    parser.add_argument("--no-restart", action="store_true", help="Skip gateway restart checks")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")


def _add_up_parser(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser("up", help="Preferred startup: doctor --fix then serve")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--store", type=str, default=None, help="Override fleet store root")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--tui", action="store_true", help="Run server with live monitor TUI (logs/compute/tokens)")
    parser.add_argument("--skip-doctor", action="store_true", help="Skip doctor pass before serving")
    parser.add_argument("--no-fix", action="store_true", help="Run doctor in validate-only mode")
    parser.add_argument("--no-restart", action="store_true", help="Skip gateway restart during doctor pass")


def _add_tools_parser(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser("tools", help="Run knowledge tools")
    tools_sub = parser.add_subparsers(dest="command", required=True)

    tools_sub.add_parser("list_disciplines")

    lp = tools_sub.add_parser("list_pages")
    lp.add_argument("--discipline", default=None)

    gs = tools_sub.add_parser("get_sheet_summary")
    gs.add_argument("page_name")

    gi = tools_sub.add_parser("get_sheet_index")
    gi.add_argument("page_name")

    lr = tools_sub.add_parser("list_regions")
    lr.add_argument("page_name")

    grd = tools_sub.add_parser("get_region_detail")
    grd.add_argument("page_name")
    grd.add_argument("region_id")

    s = tools_sub.add_parser("search")
    s.add_argument("query")

    fcr = tools_sub.add_parser("find_cross_references")
    fcr.add_argument("page_name")

    tools_sub.add_parser("list_modifications")
    tools_sub.add_parser("check_gaps")

    cw = tools_sub.add_parser("create_workspace")
    cw.add_argument("title")
    cw.add_argument("description")

    tools_sub.add_parser("list_workspaces")

    gw = tools_sub.add_parser("get_workspace")
    gw.add_argument("slug")

    ap = tools_sub.add_parser("add_page")
    ap.add_argument("slug")
    ap.add_argument("page_name")

    rp = tools_sub.add_parser("remove_page")
    rp.add_argument("slug")
    rp.add_argument("page_name")

    sp = tools_sub.add_parser("select_pointers")
    sp.add_argument("slug")
    sp.add_argument("page_name")
    sp.add_argument("pointer_ids", nargs="+")

    dp = tools_sub.add_parser("deselect_pointers")
    dp.add_argument("slug")
    dp.add_argument("page_name")
    dp.add_argument("pointer_ids", nargs="+")

    an = tools_sub.add_parser("add_note")
    an.add_argument("slug")
    an.add_argument("text")
    an.add_argument("--source_page", default=None)

    ad = tools_sub.add_parser("add_description")
    ad.add_argument("slug")
    ad.add_argument("page_name")
    ad.add_argument("description")

    hl = tools_sub.add_parser("highlight")
    hl.add_argument("slug")
    hl.add_argument("page_name")
    hl.add_argument("query")

    ch = tools_sub.add_parser("clear_highlights")
    ch.add_argument("slug")
    ch.add_argument("page_name")

    gen = tools_sub.add_parser("generate_image")
    gen.add_argument("slug")
    gen.add_argument("prompt")
    gen.add_argument("--reference_pages", nargs="*", default=None)
    gen.add_argument("--reference_image", default=None)
    gen.add_argument("--aspect_ratio", default="1:1")
    gen.add_argument("--image_size", default="2K")

    di = tools_sub.add_parser("delete_image")
    di.add_argument("slug")
    di.add_argument("filename")


def _add_index_parser(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser("index", help="Rebuild project index")
    parser.add_argument("project_dir", help="Path to project directory")


def _add_license_parser(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser("license", help="License management")
    lic_sub = parser.add_subparsers(dest="license_command", required=True)

    gen_company = lic_sub.add_parser("generate-company", help="Generate a test company license key")
    gen_company.add_argument("company_id", help="Company ID (e.g., CMP7F8A3D2E)")

    gen_project = lic_sub.add_parser("generate-project", help="Generate a test project license key")
    gen_project.add_argument("company_id", help="Company ID")
    gen_project.add_argument("project_id", help="Project ID (e.g., PRJ4B2C9A1F)")
    gen_project.add_argument(
        "project_slug",
        nargs="?",
        default=None,
        help="Project slug (auto-derived from project.json if omitted)",
    )
    gen_project.add_argument("--store", help="Knowledge store path (defaults to MAESTRO_STORE or knowledge_store)")

    lic_sub.add_parser("validate", help="Validate current license")
    lic_sub.add_parser("info", help="Show license details")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maestro",
        description="Maestro — AI that understands construction plans",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    _add_ingest_parser(subparsers)
    _add_start_parser(subparsers)
    _add_serve_parser(subparsers)
    _add_doctor_parser(subparsers)
    _add_update_parser(subparsers)
    _add_up_parser(subparsers)
    _add_tools_parser(subparsers)
    _add_index_parser(subparsers)
    _add_license_parser(subparsers)

    return parser


def _handle_start(args: argparse.Namespace):
    from .runtime import main as runtime_main

    runtime_main(port=args.port, store=str(resolve_fleet_store_root(args.store)))


def _handle_ingest(args: argparse.Namespace):
    from .ingest import ingest

    ingest(args.folder, args.project_name, args.dpi, args.store)


def _handle_serve(args: argparse.Namespace):
    from .server import app
    import maestro.server as srv
    import uvicorn

    resolved_store = resolve_fleet_store_root(args.store)
    srv.store_path = resolved_store
    srv.server_port = int(args.port)
    print(f"Maestro server starting on http://localhost:{args.port}")
    print(f"Knowledge store: {srv.store_path}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)


def _handle_update(args: argparse.Namespace):
    from .update import run_update

    code = run_update(
        workspace_override=args.workspace,
        restart_gateway=not args.no_restart,
        dry_run=args.dry_run,
    )
    if code != 0:
        sys.exit(code)


def _handle_doctor(args: argparse.Namespace):
    from .doctor import run_doctor

    code = run_doctor(
        fix=bool(args.fix),
        store_override=args.store,
        restart_gateway=not args.no_restart,
        json_output=bool(args.json),
    )
    if code != 0:
        sys.exit(code)


def _handle_up(args: argparse.Namespace):
    from .doctor import run_doctor

    resolved_store = str(resolve_fleet_store_root(args.store))
    if not args.skip_doctor:
        doctor_code = run_doctor(
            fix=not args.no_fix,
            store_override=resolved_store,
            restart_gateway=not args.no_restart,
            json_output=False,
        )
        if doctor_code != 0:
            sys.exit(doctor_code)
    if args.tui:
        from .monitor import run_up_tui

        run_up_tui(port=args.port, store=resolved_store, host=args.host)
        return
    args.store = resolved_store
    _handle_serve(args)


def _handle_index(args: argparse.Namespace):
    from .index import build_index

    idx = build_index(Path(args.project_dir))
    summary = idx["summary"]
    print(
        f"Index built: {summary['page_count']} pages, {summary['pointer_count']} pointers, "
        f"{summary['unique_material_count']} materials, {summary['unique_keyword_count']} keywords"
    )


def _run_license(args: argparse.Namespace):
    import os
    from .config import get_store_path
    from .license import (
        LicenseError,
        generate_company_key,
        generate_project_fingerprint,
        generate_project_key,
        get_machine_id,
        validate_company_key,
        validate_project_key,
    )

    if args.license_command == "generate-company":
        key = generate_company_key(args.company_id)
        print(f"\n[OK] Company License Generated:\n")
        print(f"   {key}\n")
        print("Set this as MAESTRO_LICENSE_KEY environment variable for the company agent.\n")

    elif args.license_command == "generate-project":
        store_path = args.store or os.environ.get("MAESTRO_STORE") or get_store_path()
        project_slug = args.project_slug
        if not project_slug:
            from .loader import load_project
            from .utils import slugify_underscore

            project = load_project(str(store_path))
            project_slug = project.get("slug") or slugify_underscore(project.get("name", ""))
            if not project_slug:
                print("[X] Could not derive project slug. Pass it explicitly.")
                sys.exit(1)
            print(f"Auto-derived slug: {project_slug}")

        key = generate_project_key(
            args.company_id,
            args.project_id,
            project_slug,
            str(store_path),
        )
        print(f"\n[OK] Project License Generated:\n")
        print(f"   {key}\n")
        print(f"Project: {project_slug}")
        print(f"Store:   {store_path}")
        fp = generate_project_fingerprint(project_slug, str(store_path))
        print(f"Machine: {fp['machine_id']}")
        print(f"Fingerprint: {fp['fingerprint']}\n")
        print("Set this as MAESTRO_LICENSE_KEY environment variable.\n")

    elif args.license_command == "validate":
        license_key = os.environ.get("MAESTRO_LICENSE_KEY")
        if not license_key:
            print("[ERROR] No MAESTRO_LICENSE_KEY found in environment")
            return

        try:
            if license_key.startswith("MAESTRO-COMPANY-"):
                result = validate_company_key(license_key)
                print(f"\n[OK] Valid Company License")
                print(f"   Company ID: {result['company_id']}")
                print(f"   Version: {result['version']}")
                print(f"   Issued: {result['timestamp']}\n")
            elif license_key.startswith("MAESTRO-PROJECT-"):
                from .loader import load_project
                from .utils import slugify_underscore

                store_path = os.environ.get("MAESTRO_STORE") or get_store_path()
                project = load_project(store_path=Path(store_path))
                if not project:
                    print("[ERROR] No project found in knowledge store")
                    print(f"   Store path: {store_path}")
                    return
                project_slug = project.get("slug") or slugify_underscore(project.get("name", ""))
                result = validate_project_key(license_key, project_slug, str(store_path))
                print(f"\n[OK] Valid Project License")
                print(f"   Company ID: {result['company_id']}")
                print(f"   Project ID: {result['project_id']}")
                print(f"   Version: {result['version']}")
                print(f"   Fingerprint: {result['fingerprint']}")
                print(f"   Machine: {result['fingerprint_data']['machine_id']}")
                print(f"   Issued: {result['timestamp']}\n")
            else:
                print(f"[ERROR] Unknown license key format: {license_key[:20]}...")
        except LicenseError as e:
            print(f"\n[ERROR] License validation failed:\n   {e}\n")

    elif args.license_command == "info":
        license_key = os.environ.get("MAESTRO_LICENSE_KEY")
        if not license_key:
            print("[ERROR] No MAESTRO_LICENSE_KEY found in environment")
            return

        parts = license_key.split("-")
        print(f"\n[INFO] License Information:\n")
        print(f"   Type: {parts[1] if len(parts) > 1 else 'Unknown'}")
        print(f"   Key: {license_key[:40]}...")

        if license_key.startswith("MAESTRO-COMPANY-"):
            try:
                result = validate_company_key(license_key)
                print("   Status: Valid")
                print(f"   Company: {result['company_id']}")
                print(f"   Version: {result['version']}")
                print(f"   Issued: {result['timestamp']}")
            except LicenseError:
                print("   Status: Invalid")

        elif license_key.startswith("MAESTRO-PROJECT-"):
            print(f"   Company: {parts[3] if len(parts) > 3 else 'N/A'}")
            print(f"   Project: {parts[4] if len(parts) > 4 else 'N/A'}")
            print(f"   Fingerprint: {parts[6] if len(parts) > 6 else 'N/A'}")
            print(f"\n   Machine ID: {get_machine_id()}")

        print()


def _run_tools(args: argparse.Namespace):
    import os
    from .config import load_dotenv
    from .tools import MaestroTools

    workspace = os.environ.get("MAESTRO_WORKSPACE")
    load_dotenv(Path(workspace) if workspace else None)

    workspace_path = Path(workspace) if workspace else None
    if is_company_role(workspace_path):
        print(json.dumps({
            "error": "Company Maestro is control-plane only. Project knowledge tools are disabled here.",
            "next_step": "Route the question to a project maestro node from Command Center.",
        }, indent=2))
        return

    store = os.environ.get("MAESTRO_STORE", "knowledge_store")
    try:
        tools = MaestroTools(
            store_path=store,
            workspace_root=workspace_path,
        )
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return

    commands = {
        "list_disciplines": lambda: tools.list_disciplines(),
        "list_pages": lambda: tools.list_pages(getattr(args, "discipline", None)),
        "get_sheet_summary": lambda: tools.get_sheet_summary(args.page_name),
        "get_sheet_index": lambda: tools.get_sheet_index(args.page_name),
        "list_regions": lambda: tools.list_regions(args.page_name),
        "get_region_detail": lambda: tools.get_region_detail(args.page_name, args.region_id),
        "search": lambda: tools.search(args.query),
        "find_cross_references": lambda: tools.find_cross_references(args.page_name),
        "list_modifications": lambda: tools.list_modifications(),
        "check_gaps": lambda: tools.check_gaps(),
        "create_workspace": lambda: tools.create_workspace(args.title, args.description),
        "list_workspaces": lambda: tools.list_workspaces(),
        "get_workspace": lambda: tools.get_workspace(args.slug),
        "add_page": lambda: tools.add_workspace_page(args.slug, args.page_name),
        "remove_page": lambda: tools.remove_workspace_page(args.slug, args.page_name),
        "select_pointers": lambda: tools.select_pointers(args.slug, args.page_name, args.pointer_ids),
        "deselect_pointers": lambda: tools.deselect_pointers(args.slug, args.page_name, args.pointer_ids),
        "add_note": lambda: tools.add_note(args.slug, args.text, getattr(args, "source_page", None)),
        "add_description": lambda: tools.add_page_description(args.slug, args.page_name, args.description),
        "highlight": lambda: tools.highlight(args.slug, args.page_name, args.query),
        "clear_highlights": lambda: tools.clear_highlights(args.slug, args.page_name),
        "generate_image": lambda: tools.generate_image(
            args.slug,
            args.prompt,
            reference_pages=args.reference_pages,
            reference_image_path=getattr(args, "reference_image", None),
            aspect_ratio=args.aspect_ratio,
            image_size=args.image_size,
        ),
        "delete_image": lambda: tools.delete_image(args.slug, args.filename),
    }

    result = commands[args.command]()
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "start": _handle_start,
        "ingest": _handle_ingest,
        "serve": _handle_serve,
        "doctor": _handle_doctor,
        "update": _handle_update,
        "up": _handle_up,
        "index": _handle_index,
        "license": _run_license,
        "tools": _run_tools,
    }
    handlers[args.mode](args)


if __name__ == "__main__":
    main()
