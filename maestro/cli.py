"""
Maestro CLI — unified entry point for all Maestro commands.

Usage:
    maestro ingest <folder> [options]
    maestro serve [options]
    maestro tools <command> [args]
"""

from __future__ import annotations

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="maestro",
        description="Maestro — AI that understands construction plans",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    # ── maestro ingest ────────────────────────────────────────────────────────
    ingest_parser = sub.add_parser("ingest", help="Ingest PDFs into knowledge store")
    ingest_parser.add_argument("folder", help="Path to folder containing PDFs")
    ingest_parser.add_argument("--project-name", "-n", help="Project name")
    ingest_parser.add_argument("--dpi", type=int, default=200, help="Render DPI (default: 200)")
    ingest_parser.add_argument("--store", help="Override knowledge_store path")

    # ── maestro serve ─────────────────────────────────────────────────────────
    serve_parser = sub.add_parser("serve", help="Start the frontend server")
    serve_parser.add_argument("--port", type=int, default=3000)
    serve_parser.add_argument("--store", type=str, default="knowledge_store")
    serve_parser.add_argument("--host", type=str, default="0.0.0.0")

    # ── maestro tools ─────────────────────────────────────────────────────────
    tools_parser = sub.add_parser("tools", help="Run knowledge tools")
    tools_sub = tools_parser.add_subparsers(dest="command", required=True)

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

    # Workspace commands
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

    # ── maestro index ─────────────────────────────────────────────────────────
    idx_parser = sub.add_parser("index", help="Rebuild project index")
    idx_parser.add_argument("project_dir", help="Path to project directory")

    # ── maestro license ───────────────────────────────────────────────────────
    lic_parser = sub.add_parser("license", help="License management")
    lic_sub = lic_parser.add_subparsers(dest="license_command", required=True)

    gen_company = lic_sub.add_parser("generate-company", help="Generate a test company license key")
    gen_company.add_argument("company_id", help="Company ID (e.g., CMP7F8A3D2E)")

    gen_project = lic_sub.add_parser("generate-project", help="Generate a test project license key")
    gen_project.add_argument("company_id", help="Company ID")
    gen_project.add_argument("project_id", help="Project ID (e.g., PRJ4B2C9A1F)")
    gen_project.add_argument("project_slug", help="Project slug (e.g., chick-fil-a-love-field)")
    gen_project.add_argument("--store", help="Knowledge store path (defaults to MAESTRO_STORE or knowledge_store)")

    lic_sub.add_parser("validate", help="Validate current license")

    lic_sub.add_parser("info", help="Show license details")

    args = parser.parse_args()

    if args.mode == "ingest":
        from .ingest import ingest
        ingest(args.folder, args.project_name, args.dpi, args.store)

    elif args.mode == "serve":
        _run_server(args)

    elif args.mode == "index":
        from .index import build_index
        from pathlib import Path
        idx = build_index(Path(args.project_dir))
        s = idx["summary"]
        print(f"Index built: {s['page_count']} pages, {s['pointer_count']} pointers, "
              f"{s['unique_material_count']} materials, {s['unique_keyword_count']} keywords")

    elif args.mode == "license":
        _run_license(args)

    elif args.mode == "tools":
        _run_tools(args)


def _run_server(args):
    """Start the Maestro server."""
    # Import server module (keeps FastAPI deps lazy)
    from .server import app, store_path as _sp
    import maestro.server as srv
    from pathlib import Path
    import uvicorn

    srv.store_path = Path(args.store).resolve()
    print(f"Maestro server starting on http://localhost:{args.port}")
    print(f"Knowledge store: {srv.store_path}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def _run_license(args):
    """Run license management commands."""
    import os
    from pathlib import Path
    from .license import (
        generate_company_key,
        generate_project_key,
        validate_company_key,
        validate_project_key,
        get_machine_id,
        generate_project_fingerprint,
        LicenseError,
    )
    from .config import get_store_path

    if args.license_command == "generate-company":
        key = generate_company_key(args.company_id)
        print(f"\n[OK] Company License Generated:\n")
        print(f"   {key}\n")
        print(f"Set this as MAESTRO_LICENSE_KEY environment variable for the company agent.\n")

    elif args.license_command == "generate-project":
        store_path = args.store or os.environ.get("MAESTRO_STORE") or get_store_path()
        key = generate_project_key(
            args.company_id,
            args.project_id,
            args.project_slug,
            str(store_path),
        )
        print(f"\n[OK] Project License Generated:\n")
        print(f"   {key}\n")
        print(f"Project: {args.project_slug}")
        print(f"Store:   {store_path}")
        fp = generate_project_fingerprint(args.project_slug, str(store_path))
        print(f"Machine: {fp['machine_id']}")
        print(f"Fingerprint: {fp['fingerprint']}\n")
        print(f"Set this as MAESTRO_LICENSE_KEY environment variable.\n")

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
                from .utils import slugify_underscore
                from .loader import load_project
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
                print(f"   Status: Valid")
                print(f"   Company: {result['company_id']}")
                print(f"   Version: {result['version']}")
                print(f"   Issued: {result['timestamp']}")
            except LicenseError:
                print(f"   Status: Invalid")

        elif license_key.startswith("MAESTRO-PROJECT-"):
            print(f"   Company: {parts[3] if len(parts) > 3 else 'N/A'}")
            print(f"   Project: {parts[4] if len(parts) > 4 else 'N/A'}")
            print(f"   Fingerprint: {parts[6] if len(parts) > 6 else 'N/A'}")
            print(f"\n   Machine ID: {get_machine_id()}")

        print()


def _run_tools(args):
    """Run a tools command and print JSON output."""
    from .tools import MaestroTools
    import os
    from pathlib import Path

    store = os.environ.get("MAESTRO_STORE", "knowledge_store")
    workspace = os.environ.get("MAESTRO_WORKSPACE")
    tools = MaestroTools(
        store_path=store,
        workspace_root=Path(workspace) if workspace else None,
    )

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
            args.slug, args.prompt,
            reference_pages=args.reference_pages,
            reference_image_path=getattr(args, "reference_image", None),
            aspect_ratio=args.aspect_ratio,
            image_size=args.image_size,
        ),
        "delete_image": lambda: tools.delete_image(args.slug, args.filename),
    }

    result = commands[args.command]()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
