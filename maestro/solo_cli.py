"""Solo-only CLI surface for install, purchase, status, and runtime startup."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .solo_license import load_local_license, save_local_license, verify_solo_license_key


DEFAULT_BILLING_URL = "http://127.0.0.1:8081"
DEFAULT_LICENSE_URL = "http://127.0.0.1:8082"
DEFAULT_PLAN = "solo_test_monthly"
CYAN = "cyan"
BRIGHT_CYAN = "bright_cyan"
DIM = "dim"

console = Console()


def _open_url(url: str):
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


def _print_json(payload: dict[str, Any]):
    print(json.dumps(payload, indent=2))


def _billing_url(value: str | None) -> str:
    text = str(value or "").strip()
    if text:
        return text.rstrip("/")
    env = str(os.environ.get("MAESTRO_BILLING_URL", "")).strip()
    if env:
        return env.rstrip("/")
    return DEFAULT_BILLING_URL


def _license_url(value: str | None) -> str:
    text = str(value or "").strip()
    if text:
        return text.rstrip("/")
    env = str(os.environ.get("MAESTRO_LICENSE_URL", "")).strip()
    if env:
        return env.rstrip("/")
    return DEFAULT_LICENSE_URL


def _http_post_json(url: str, payload: dict[str, Any], timeout: int = 20) -> tuple[bool, dict[str, Any]]:
    try:
        response = httpx.post(url, json=payload, timeout=timeout)
    except Exception as exc:
        return False, {"error": f"http_post_failed: {exc}"}
    try:
        data = response.json()
    except Exception:
        data = {"error": response.text}
    if response.status_code >= 300:
        return False, {
            "error": f"http_status_{response.status_code}",
            "detail": data,
        }
    return True, data if isinstance(data, dict) else {"result": data}


def _http_get_json(url: str, timeout: int = 20) -> tuple[bool, dict[str, Any]]:
    try:
        response = httpx.get(url, timeout=timeout)
    except Exception as exc:
        return False, {"error": f"http_get_failed: {exc}"}
    try:
        data = response.json()
    except Exception:
        data = {"error": response.text}
    if response.status_code >= 300:
        return False, {
            "error": f"http_status_{response.status_code}",
            "detail": data,
        }
    return True, data if isinstance(data, dict) else {"result": data}


def _cmd_install(_: argparse.Namespace) -> int:
    from .cli import main as maestro_main

    console.print(Panel(
        "[white]Launching existing Maestro setup flow[/]\n"
        f"[{DIM}]Reuses the same prerequisite checks and setup UI as `maestro setup`.[/]",
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]Maestro Solo Setup[/]",
    ))
    maestro_main(["setup"])
    return 0


def _cmd_purchase(args: argparse.Namespace) -> int:
    email = str(args.email or "").strip()
    if not email:
        if bool(getattr(args, "non_interactive", False)):
            console.print("[red]Missing --email in non-interactive mode.[/]")
            return 1
        email = Prompt.ask("Email for receipt/license").strip()

    if "@" not in email:
        console.print("[red]Please provide a valid email address.[/]")
        return 1

    billing = _billing_url(args.billing_url)
    payload = {
        "email": email,
        "plan_id": args.plan.strip(),
        "mode": str(args.mode).strip() or "test",
        "success_url": str(args.success_url or "").strip() or "http://localhost/success",
        "cancel_url": str(args.cancel_url or "").strip() or "http://localhost/cancel",
    }

    console.print(Panel(
        "\n".join([
            f"Email: {payload['email']}",
            f"Plan: {payload['plan_id']}",
            f"Mode: {payload['mode']}",
            f"Billing API: {billing}",
        ]),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]Maestro Solo Purchase[/]",
    ))

    ok, create = _http_post_json(f"{billing}/v1/solo/purchases", payload, timeout=20)
    if not ok:
        console.print("[red]Failed to create purchase.[/]")
        _print_json(create)
        return 1

    purchase_id = str(create.get("purchase_id", "")).strip()
    checkout_url = str(create.get("checkout_url", "")).strip()
    if not purchase_id or not checkout_url:
        console.print("[red]Billing response missing purchase_id or checkout_url.[/]")
        _print_json(create)
        return 1

    console.print(Panel(
        "\n".join([
            f"purchase_id: {purchase_id}",
            f"checkout_url: {checkout_url}",
        ]),
        border_style="green",
        title="[bold green]Purchase Created[/]",
    ))
    if not args.no_open:
        _open_url(checkout_url)
        console.print(f"[{DIM}]Opened checkout in browser.[/]")
    else:
        console.print(f"[{DIM}]Checkout auto-open disabled (--no-open).[/]")

    if payload["mode"] == "test":
        console.print("")
        console.print("[bold]Test mode helper:[/]")
        console.print(
            f"curl -sS -X POST {billing}/v1/solo/dev/mark-paid "
            f"-H 'content-type: application/json' -d '{json.dumps({'purchase_id': purchase_id})}'"
        )

    deadline = time.time() + max(10, int(args.timeout_seconds))
    poll_seconds = max(1, int(args.poll_seconds))
    last_status = ""
    console.print("")
    console.print("[bold]Waiting for payment confirmation...[/]")

    while time.time() < deadline:
        ok, polled = _http_get_json(f"{billing}/v1/solo/purchases/{purchase_id}", timeout=20)
        if not ok:
            console.print("[yellow]Polling failed; retrying...[/]")
            _print_json(polled)
            time.sleep(poll_seconds)
            continue

        status = str(polled.get("status", "")).strip().lower()
        if status and status != last_status:
            console.print(f"[{CYAN}]status:[/] {status}")
            last_status = status

        if status == "licensed":
            license_key = str(polled.get("license_key", "")).strip()
            if not license_key:
                console.print("[red]Purchase is licensed but license key is empty.[/]")
                _print_json(polled)
                return 1
            verify = verify_solo_license_key(license_key)
            if not bool(verify.get("valid")):
                console.print("[red]Received invalid license key from billing flow.[/]")
                _print_json(verify)
                return 1
            saved = save_local_license(license_key, source="billing_service")
            console.print(Panel(
                "\n".join([
                    "License provisioned and saved locally.",
                    f"sku: {saved.get('sku', '')}",
                    f"plan_id: {saved.get('plan_id', '')}",
                    f"expires_at: {saved.get('expires_at', '')}",
                ]),
                border_style="green",
                title="[bold green]Solo License Active[/]",
            ))
            return 0

        if status in {"failed", "canceled"}:
            console.print("[red]Purchase did not complete.[/]")
            _print_json(polled)
            return 1

        time.sleep(poll_seconds)

    console.print(Panel(
        "\n".join([
            "Timed out waiting for license provisioning.",
            f"purchase_id: {purchase_id}",
            f"poll_url: {billing}/v1/solo/purchases/{purchase_id}",
        ]),
        border_style="yellow",
        title="[bold yellow]Purchase Pending[/]",
    ))
    return 1


def _cmd_status(args: argparse.Namespace) -> int:
    local = load_local_license()
    if not local:
        console.print(Panel(
            "No local Solo license found.\n"
            "Run: [bold white]maestro-solo purchase[/]",
            border_style="yellow",
            title="[bold yellow]License Missing[/]",
        ))
        return 1

    key = str(local.get("license_key", "")).strip()
    verify = verify_solo_license_key(key)
    payload: dict[str, Any] = {
        "local_license_present": True,
        "local_valid": bool(verify.get("valid")),
        "sku": str(verify.get("sku", "")),
        "plan_id": str(verify.get("plan_id", "")),
        "purchase_id": str(verify.get("purchase_id", "")),
        "email": str(verify.get("email", "")),
        "issued_at": str(verify.get("issued_at", "")),
        "expires_at": str(verify.get("expires_at", "")),
        "error": str(verify.get("error", "")),
    }

    if args.remote_verify:
        url = f"{_license_url(args.license_url)}/v1/licenses/solo/verify"
        ok, remote = _http_post_json(url, {"license_key": key}, timeout=20)
        payload["remote_verify_ok"] = ok
        payload["remote_verify"] = remote

    if args.json:
        _print_json(payload)
    else:
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_row("local_valid", str(payload["local_valid"]))
        table.add_row("plan_id", str(payload["plan_id"]))
        table.add_row("purchase_id", str(payload["purchase_id"]))
        table.add_row("email", str(payload["email"]))
        table.add_row("expires_at", str(payload["expires_at"]))
        if payload["error"]:
            table.add_row("error", str(payload["error"]))
        if "remote_verify_ok" in payload:
            table.add_row("remote_verify_ok", str(payload["remote_verify_ok"]))
        console.print(Panel(
            table,
            border_style="green" if bool(payload["local_valid"]) else "yellow",
            title="[bold bright_cyan]Maestro Solo License Status[/]",
        ))
    return 0 if bool(payload.get("local_valid")) else 1


def _cmd_up(args: argparse.Namespace) -> int:
    local = load_local_license()
    key = str(local.get("license_key", "")).strip()
    verify = verify_solo_license_key(key)
    if not bool(verify.get("valid")):
        console.print(Panel(
            "No valid Solo license found.\n"
            "Run: [bold white]maestro-solo purchase[/]",
            border_style="red",
            title="[bold red]Cannot Start[/]",
        ))
        return 1

    console.print(f"[{CYAN}]Starting Maestro Solo workspace...[/]")
    passthrough: list[str] = ["up"]
    passthrough += ["--port", str(args.port)]
    passthrough += ["--host", str(args.host)]
    if args.store:
        passthrough += ["--store", str(args.store)]
    if args.tui:
        passthrough.append("--tui")
    if args.skip_doctor:
        passthrough.append("--skip-doctor")
    if args.no_fix:
        passthrough.append("--no-fix")
    if args.no_restart:
        passthrough.append("--no-restart")
    if args.field_access_required:
        passthrough.append("--field-access-required")

    from .cli import main as maestro_main

    maestro_main(passthrough)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maestro-solo",
        description="Maestro Solo CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Run Solo setup wizard")

    purchase = sub.add_parser("purchase", help="Create Solo purchase and wait for license provisioning")
    purchase.add_argument("--email", default="")
    purchase.add_argument("--plan", default=DEFAULT_PLAN)
    purchase.add_argument("--mode", default="test", choices=["test", "live"], help=argparse.SUPPRESS)
    purchase.add_argument("--billing-url", default=None, help=argparse.SUPPRESS)
    purchase.add_argument("--success-url", default=None, help=argparse.SUPPRESS)
    purchase.add_argument("--cancel-url", default=None, help=argparse.SUPPRESS)
    purchase.add_argument("--poll-seconds", type=int, default=3, help=argparse.SUPPRESS)
    purchase.add_argument("--timeout-seconds", type=int, default=300, help=argparse.SUPPRESS)
    purchase.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)
    purchase.add_argument("--non-interactive", action="store_true", help=argparse.SUPPRESS)

    status = sub.add_parser("status", help="Show local Solo license status")
    status.add_argument("--json", action="store_true")
    status.add_argument("--remote-verify", action="store_true")
    status.add_argument("--license-url", default=None)

    up = sub.add_parser("up", help="Start Solo runtime (requires valid local license)")
    up.add_argument("--port", type=int, default=3000)
    up.add_argument("--host", type=str, default="0.0.0.0")
    up.add_argument("--store", type=str, default=None)
    up.add_argument("--tui", action="store_true")
    up.add_argument("--skip-doctor", action="store_true")
    up.add_argument("--no-fix", action="store_true")
    up.add_argument("--no-restart", action="store_true")
    up.add_argument("--field-access-required", action="store_true")

    return parser


def main(argv: list[str] | None = None):
    parsed_argv = list(argv) if argv is not None else None
    if parsed_argv and parsed_argv[0] == "install":
        parsed_argv[0] = "setup"
    args = build_parser().parse_args(parsed_argv)
    handlers = {
        "setup": _cmd_install,
        "purchase": _cmd_purchase,
        "status": _cmd_status,
        "up": _cmd_up,
    }
    code = handlers[args.command](args)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
