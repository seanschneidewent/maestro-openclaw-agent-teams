"""Standalone CLI surface for Maestro Solo."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from maestro_engine.utils import slugify

from .entitlements import (
    clear_local_entitlement,
    entitlement_label,
    load_local_entitlement,
    normalize_tier,
    resolve_effective_entitlement,
    save_local_entitlement,
)
from .install_state import (
    load_install_state,
    record_active_project,
    resolve_solo_store_root,
    update_install_state,
)
from .migration import migrate_legacy, print_migration_report
from .solo_license import load_local_license, save_local_license, verify_solo_license_key


DEFAULT_BILLING_URL = (
    os.environ.get("MAESTRO_BILLING_URL_DEFAULT", "https://maestro-billing-service-production.up.railway.app")
    .strip()
    .rstrip("/")
)
if not DEFAULT_BILLING_URL:
    DEFAULT_BILLING_URL = "https://maestro-billing-service-production.up.railway.app"

DEFAULT_LICENSE_URL = (
    os.environ.get("MAESTRO_LICENSE_URL_DEFAULT", "https://maestro-license-service-production.up.railway.app")
    .strip()
    .rstrip("/")
)
if not DEFAULT_LICENSE_URL:
    DEFAULT_LICENSE_URL = "https://maestro-license-service-production.up.railway.app"
DEFAULT_PLAN = "solo_monthly"
DEFAULT_PURCHASE_MODE = (
    os.environ.get("MAESTRO_SOLO_PURCHASE_MODE", "live").strip().lower() or "live"
)
if DEFAULT_PURCHASE_MODE not in {"test", "live"}:
    DEFAULT_PURCHASE_MODE = "live"
CYAN = "cyan"
BRIGHT_CYAN = "bright_cyan"
DIM = "dim"

console = Console()


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


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


def _solo_home() -> Path:
    raw = _clean_text(os.environ.get("MAESTRO_SOLO_HOME"))
    return Path(raw).expanduser().resolve() if raw else (Path.home() / ".maestro-solo").resolve()


def _auth_cache_path() -> Path:
    return _solo_home() / "auth.json"


def _load_auth_cache() -> dict[str, Any]:
    path = _auth_cache_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_auth_cache(payload: dict[str, Any]):
    path = _auth_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _clear_auth_cache():
    path = _auth_cache_path()
    if path.exists():
        path.unlink(missing_ok=True)


def _local_access_token() -> str:
    return _clean_text(_load_auth_cache().get("access_token"))


def _auth_headers(required: bool = False) -> dict[str, str]:
    token = _local_access_token()
    if not token:
        if required:
            raise RuntimeError("auth_required: run 'maestro-solo auth login'")
        return {}
    return {"Authorization": f"Bearer {token}"}


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


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    timeout: int = 20,
    headers: dict[str, str] | None = None,
) -> tuple[bool, dict[str, Any]]:
    try:
        response = httpx.post(url, json=payload, timeout=timeout, headers=headers)
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


def _http_get_json(
    url: str,
    timeout: int = 20,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    try:
        response = httpx.get(url, timeout=timeout, headers=headers, params=params)
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


def _cmd_setup(args: argparse.Namespace) -> int:
    if bool(getattr(args, "quick", False)):
        from .quick_setup import run_quick_setup

        return run_quick_setup(
            company_name=str(getattr(args, "company_name", "")).strip(),
            replay=bool(getattr(args, "replay", False)),
        )

    from .setup_wizard import main as setup_main

    setup_main()
    return 0


def _cmd_auth(args: argparse.Namespace) -> int:
    action = _clean_text(getattr(args, "auth_action", "")).lower() or "status"
    billing = _billing_url(getattr(args, "billing_url", None))

    if action == "logout":
        headers = _auth_headers(required=False)
        if headers:
            _http_post_json(f"{billing}/v1/auth/logout", {}, timeout=20, headers=headers)
        _clear_auth_cache()
        console.print("[green]Signed out from local Maestro auth cache.[/]")
        return 0

    if action == "status":
        headers = _auth_headers(required=False)
        if not headers:
            payload = {
                "authenticated": False,
                "email": "",
                "sub": "",
                "detail": "not_signed_in",
            }
            if bool(getattr(args, "json", False)):
                _print_json(payload)
                return 0
            console.print(Panel(
                "\n".join([
                    "Not signed in.",
                    "Google sign-in is optional for Free.",
                    "Google sign-in is required before Pro purchase.",
                ]),
                border_style="yellow",
                title="[bold yellow]Maestro Auth[/]",
            ))
            return 0
        ok, payload = _http_get_json(f"{billing}/v1/auth/session", timeout=20, headers=headers)
        if not ok or not bool(payload.get("authenticated")):
            console.print("[yellow]Auth token is missing or expired. Run: maestro-solo auth login[/]")
            if bool(getattr(args, "json", False)):
                _print_json({"authenticated": False, "detail": payload})
            return 1
        if bool(getattr(args, "json", False)):
            _print_json(payload)
            return 0
        console.print(Panel(
            "\n".join([
                "Signed in.",
                f"email: {payload.get('email', '')}",
                f"sub: {payload.get('sub', '')}",
            ]),
            border_style="green",
            title="[bold green]Maestro Auth[/]",
        ))
        return 0

    if action != "login":
        console.print(f"[red]Unknown auth action: {action}[/]")
        return 1

    # Reuse existing token if still valid.
    headers = _auth_headers(required=False)
    if headers:
        ok, payload = _http_get_json(f"{billing}/v1/auth/session", timeout=20, headers=headers)
        if ok and bool(payload.get("authenticated")):
            console.print(f"[green]Already signed in as {payload.get('email', '')}.[/]")
            return 0
        _clear_auth_cache()

    ok, created = _http_post_json(
        f"{billing}/v1/auth/cli/sessions",
        {"return_to": "/upgrade"},
        timeout=20,
    )
    if not ok:
        console.print("[red]Failed to start Google auth session.[/]")
        _print_json(created)
        return 1

    session_id = _clean_text(created.get("session_id"))
    poll_token = _clean_text(created.get("poll_token"))
    authorize_url = _clean_text(created.get("authorize_url"))
    poll_url = _clean_text(created.get("poll_url")) or f"{billing}/v1/auth/cli/sessions/{session_id}"
    if not session_id or not poll_token or not authorize_url:
        console.print("[red]Auth session response missing required fields.[/]")
        _print_json(created)
        return 1

    console.print(Panel(
        "\n".join([
            "Google sign-in is required.",
            f"authorize_url: {authorize_url}",
        ]),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]Maestro Auth Login[/]",
    ))

    if not bool(getattr(args, "no_open", False)):
        _open_url(authorize_url)
        console.print(f"[{DIM}]Opened Google sign-in in browser.[/]")
    else:
        console.print(f"[{DIM}]Auto-open disabled (--no-open).[/]")

    timeout_seconds = max(30, int(getattr(args, "timeout_seconds", 180)))
    poll_seconds = max(1, int(getattr(args, "poll_seconds", 2)))
    deadline = time.time() + timeout_seconds
    last_status = ""
    while time.time() < deadline:
        ok, polled = _http_get_json(
            poll_url,
            timeout=20,
            params={"poll_token": poll_token},
        )
        if not ok:
            time.sleep(poll_seconds)
            continue
        status = _clean_text(polled.get("status")).lower()
        if status and status != last_status:
            console.print(f"[{CYAN}]auth status:[/] {status}")
            last_status = status
        if status == "authenticated":
            access_token = _clean_text(polled.get("access_token"))
            if not access_token:
                console.print("[red]Auth completed but access_token is missing.[/]")
                _print_json(polled)
                return 1
            _save_auth_cache(
                {
                    "access_token": access_token,
                    "sub": _clean_text(polled.get("sub")),
                    "email": _clean_text(polled.get("email")),
                    "name": _clean_text(polled.get("name")),
                    "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            )
            console.print(f"[green]Signed in as {_clean_text(polled.get('email'))}.[/]")
            return 0
        if status == "expired":
            console.print("[red]Google auth session expired. Run the command again.[/]")
            return 1
        time.sleep(poll_seconds)

    console.print("[red]Timed out waiting for Google authentication.[/]")
    return 1


def _build_purchase_payload(args: argparse.Namespace, *, email: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "email": email,
        "plan_id": args.plan.strip(),
        "mode": _clean_text(args.mode) or "test",
    }
    success_url = _clean_text(getattr(args, "success_url", ""))
    if success_url:
        payload["success_url"] = success_url
    cancel_url = _clean_text(getattr(args, "cancel_url", ""))
    if cancel_url:
        payload["cancel_url"] = cancel_url
    return payload


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
    payload = _build_purchase_payload(args, email=email)

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

    if bool(getattr(args, "preview", False)):
        console.print(Panel(
            "\n".join([
                "Preview mode only. No checkout was started.",
                "When ready, run purchase without --preview to open secure checkout.",
            ]),
            border_style="yellow",
            title="[bold yellow]Purchase Preview[/]",
        ))
        return 0

    try:
        headers = _auth_headers(required=True)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    ok, create = _http_post_json(f"{billing}/v1/solo/purchases", payload, timeout=20, headers=headers)
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
        console.print("[bold]Test mode helper (requires MAESTRO_ENABLE_DEV_ENDPOINTS=1):[/]")
        auth_header = _clean_text(headers.get("Authorization", ""))
        curl_cmd = (
            f"curl -sS -X POST {billing}/v1/solo/dev/mark-paid "
            "-H 'content-type: application/json' "
        )
        if auth_header:
            curl_cmd += f"-H 'Authorization: {auth_header}' "
        curl_cmd += f"-d '{json.dumps({'purchase_id': purchase_id})}'"
        console.print(curl_cmd)

    deadline = time.time() + max(10, int(args.timeout_seconds))
    poll_seconds = max(1, int(args.poll_seconds))
    last_status = ""
    console.print("")
    console.print("[bold]Waiting for payment confirmation...[/]")

    while time.time() < deadline:
        ok, polled = _http_get_json(f"{billing}/v1/solo/purchases/{purchase_id}", timeout=20, headers=headers)
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
            entitlement_token = _clean_text(polled.get("entitlement_token"))
            entitlement_saved = {}
            if entitlement_token:
                entitlement_saved = save_local_entitlement(entitlement_token, source="billing_service")
                if bool(entitlement_saved.get("valid")):
                    console.print(f"[{DIM}]Saved Pro entitlement token.[/]")
                else:
                    console.print(f"[yellow]Received entitlement token but validation failed: {entitlement_saved.get('error', 'unknown')}[/]")
            effective = resolve_effective_entitlement()
            console.print(Panel(
                "\n".join([
                    "License provisioned and saved locally.",
                    f"sku: {saved.get('sku', '')}",
                    f"plan_id: {saved.get('plan_id', '')}",
                    f"expires_at: {saved.get('expires_at', '')}",
                    f"effective_tier: {normalize_tier(str(effective.get('tier', 'core')))}",
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


def _cmd_unsubscribe(args: argparse.Namespace) -> int:
    billing = _billing_url(args.billing_url)
    try:
        headers = _auth_headers(required=True)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    local = load_local_license()
    purchase_id = _clean_text(args.purchase_id) or _clean_text(local.get("purchase_id"))
    email = _clean_text(args.email) or _clean_text(local.get("email"))
    return_url = _clean_text(args.return_url)

    if not purchase_id and not email:
        console.print("[red]No purchase context found. Provide --purchase-id or --email.[/]")
        return 1

    payload: dict[str, Any] = {}
    if purchase_id:
        payload["purchase_id"] = purchase_id
    if email:
        payload["email"] = email
    if return_url:
        payload["return_url"] = return_url

    console.print(Panel(
        "\n".join([
            f"Billing API: {billing}",
            f"purchase_id: {purchase_id or '(lookup by email)'}",
            f"email: {email or '(not provided)'}",
        ]),
        border_style=CYAN,
        title=f"[bold {BRIGHT_CYAN}]Manage Subscription[/]",
    ))

    ok, created = _http_post_json(f"{billing}/v1/solo/portal-sessions", payload, timeout=20, headers=headers)
    if not ok:
        console.print("[red]Failed to create billing portal session.[/]")
        _print_json(created)
        return 1

    portal_url = _clean_text(created.get("portal_url"))
    if not portal_url:
        console.print("[red]Billing portal response missing portal_url.[/]")
        _print_json(created)
        return 1

    console.print(Panel(
        "\n".join([
            "Stripe customer portal ready.",
            f"portal_url: {portal_url}",
            "Use this page to cancel or manage your subscription.",
        ]),
        border_style="green",
        title="[bold green]Portal Session Created[/]",
    ))
    if not args.no_open:
        _open_url(portal_url)
        console.print(f"[{DIM}]Opened billing portal in browser.[/]")
    else:
        console.print(f"[{DIM}]Portal auto-open disabled (--no-open).[/]")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    local = load_local_license()
    key = str(local.get("license_key", "")).strip()
    verify = verify_solo_license_key(key) if key else {"valid": False, "error": "missing_license_key"}
    local_entitlement = load_local_entitlement()
    effective = resolve_effective_entitlement()
    payload: dict[str, Any] = {
        "local_license_present": bool(key),
        "local_valid": bool(verify.get("valid")),
        "sku": str(verify.get("sku", "")),
        "plan_id": str(verify.get("plan_id", "")),
        "purchase_id": str(verify.get("purchase_id", "")),
        "email": str(verify.get("email", "")),
        "issued_at": str(verify.get("issued_at", "")),
        "expires_at": str(verify.get("expires_at", "")),
        "error": str(verify.get("error", "")),
        "entitlement_cached": bool(_clean_text(local_entitlement.get("entitlement_token"))),
        "entitlement_valid": bool(local_entitlement.get("valid")),
        "entitlement_error": str(local_entitlement.get("error", "")),
        "entitlement_expires_at": str(local_entitlement.get("expires_at", "")),
        "tier": normalize_tier(str(effective.get("tier", "core"))),
        "capabilities": list(effective.get("capabilities", [])) if isinstance(effective.get("capabilities"), list) else [],
        "tier_source": str(effective.get("source", "")),
    }

    if args.remote_verify and key:
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
        table.add_row("tier", f"{payload['tier']} ({payload['tier_source']})")
        table.add_row("capabilities", ", ".join(payload["capabilities"]) if payload["capabilities"] else "none")
        if payload["error"]:
            table.add_row("error", str(payload["error"]))
        if payload["entitlement_cached"]:
            table.add_row("entitlement_cached", "true")
            table.add_row("entitlement_valid", str(payload["entitlement_valid"]))
            if payload["entitlement_expires_at"]:
                table.add_row("entitlement_expires", str(payload["entitlement_expires_at"]))
            if payload["entitlement_error"]:
                table.add_row("entitlement_error", str(payload["entitlement_error"]))
        if "remote_verify_ok" in payload:
            table.add_row("remote_verify_ok", str(payload["remote_verify_ok"]))
        console.print(Panel(
            table,
            border_style="green" if str(payload["tier"]) == "pro" else "yellow",
            title="[bold bright_cyan]Maestro Solo Runtime Status[/]",
        ))
    return 0


def _cmd_entitlements(args: argparse.Namespace) -> int:
    action = str(getattr(args, "entitlement_action", "")).strip().lower()
    if action == "clear":
        clear_local_entitlement()
        console.print("[green]Local entitlement cache cleared.[/]")
        return 0

    if action == "activate":
        token = str(getattr(args, "token", "")).strip()
        if not token:
            token = Prompt.ask("Entitlement token").strip()
        if not token:
            console.print("[red]Entitlement token is required.[/]")
            return 1
        saved = save_local_entitlement(token, source="cli_activate")
        if not bool(saved.get("valid")):
            console.print("[red]Entitlement token is invalid.[/]")
            _print_json(saved)
            return 1
        effective = resolve_effective_entitlement()
        console.print(Panel(
            "\n".join([
                "Entitlement token activated.",
                f"tier: {normalize_tier(str(saved.get('tier', 'core')))}",
                f"expires_at: {saved.get('expires_at', '')}",
                f"effective: {entitlement_label(effective)}",
            ]),
            border_style="green",
            title="[bold green]Entitlement Active[/]",
        ))
        return 0

    local_entitlement = load_local_entitlement()
    effective = resolve_effective_entitlement()
    payload = {
        "effective": entitlement_label(effective),
        "tier": normalize_tier(str(effective.get("tier", "core"))),
        "source": str(effective.get("source", "")),
        "capabilities": list(effective.get("capabilities", [])) if isinstance(effective.get("capabilities"), list) else [],
        "cached_token_present": bool(_clean_text(local_entitlement.get("entitlement_token"))),
        "cached_valid": bool(local_entitlement.get("valid")),
        "cached_error": str(local_entitlement.get("error", "")),
        "cached_expires_at": str(local_entitlement.get("expires_at", "")),
    }
    if bool(getattr(args, "json", False)):
        _print_json(payload)
        return 0

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_row("effective", str(payload["effective"]))
    table.add_row("source", str(payload["source"]))
    table.add_row("capabilities", ", ".join(payload["capabilities"]) if payload["capabilities"] else "none")
    table.add_row("cached_token", "present" if payload["cached_token_present"] else "missing")
    if payload["cached_token_present"]:
        table.add_row("cached_valid", str(payload["cached_valid"]))
        if payload["cached_expires_at"]:
            table.add_row("cached_expires_at", str(payload["cached_expires_at"]))
        if payload["cached_error"]:
            table.add_row("cached_error", str(payload["cached_error"]))
    console.print(Panel(
        table,
        border_style="green" if payload["tier"] == "pro" else "yellow",
        title="[bold bright_cyan]Entitlement Status[/]",
    ))
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    from .ingest import ingest

    resolved_store = str(resolve_solo_store_root(args.store))
    folder_name = Path(args.folder).expanduser().resolve().name
    project_name = str(args.project_name or "").strip() or folder_name

    ingest(args.folder, project_name, args.dpi, resolved_store)

    final_name = str(project_name or folder_name).strip()
    if final_name:
        active_slug = slugify(final_name)
        record_active_project(project_slug=active_slug, project_name=final_name)
        updates: dict[str, Any] = {"store_root": resolved_store}
        state = load_install_state()
        pending = state.get("pending_optional_setup")
        if isinstance(pending, list):
            filtered = [str(item).strip() for item in pending if str(item).strip() and str(item).strip() != "ingest_plans"]
            if filtered != pending:
                updates["pending_optional_setup"] = filtered
        update_install_state(updates)

    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import run_doctor

    return run_doctor(
        fix=bool(args.fix),
        store_override=args.store,
        restart_gateway=not args.no_restart,
        json_output=bool(args.json),
        field_access_required=bool(getattr(args, "field_access_required", False)),
    )


def _cmd_up(args: argparse.Namespace) -> int:
    from .doctor import run_doctor
    from .monitor import run_up_tui
    from .server import run_server

    entitlement = resolve_effective_entitlement()
    tier = normalize_tier(str(entitlement.get("tier", "core")))
    os.environ["MAESTRO_TIER"] = tier
    if bool(args.require_pro) and tier != "pro":
        console.print(Panel(
            "\n".join([
                "Pro runtime required but no active Pro entitlement found.",
                "Run: [bold white]maestro-solo purchase[/] or activate an entitlement token.",
            ]),
            border_style="red",
            title="[bold red]Cannot Start[/]",
        ))
        return 1
    if tier != "pro":
        console.print(Panel(
            "\n".join([
                "Starting in Core mode (generic tools only).",
                "Pro-native Maestro tools remain disabled until entitlement is active.",
            ]),
            border_style="yellow",
            title="[bold yellow]Core Mode[/]",
        ))

    resolved_store = str(resolve_solo_store_root(args.store))
    if not args.skip_doctor:
        doctor_code = run_doctor(
            fix=not args.no_fix,
            store_override=resolved_store,
            restart_gateway=not args.no_restart,
            json_output=False,
            field_access_required=bool(getattr(args, "field_access_required", False)),
        )
        if doctor_code != 0:
            return doctor_code

    if args.tui:
        run_up_tui(port=args.port, store=resolved_store, host=args.host)
        return 0

    run_server(port=args.port, store=resolved_store, host=args.host)
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server import run_server

    resolved_store = str(resolve_solo_store_root(args.store))
    run_server(port=args.port, store=resolved_store, host=args.host)
    return 0


def _cmd_migrate_legacy(args: argparse.Namespace) -> int:
    report = migrate_legacy(dry_run=bool(args.dry_run))
    print_migration_report(report)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maestro-solo",
        description="Maestro Solo CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="Run Solo setup wizard")
    setup.add_argument(
        "--quick",
        action="store_true",
        help="Run fast-path setup for one-command bootstrap (macOS)",
    )
    setup.add_argument(
        "--company-name",
        default="",
        help="Optional company name used by --quick",
    )
    setup.add_argument(
        "--replay",
        action="store_true",
        help="Replay quick setup checks using existing config when available",
    )

    auth = sub.add_parser("auth", help="Sign in/out and inspect Maestro billing auth session")
    auth_sub = auth.add_subparsers(dest="auth_action", required=False)
    auth_status = auth_sub.add_parser("status", help="Show current auth session status")
    auth_status.add_argument("--billing-url", default=None)
    auth_status.add_argument("--json", action="store_true")
    auth_login = auth_sub.add_parser("login", help="Sign in with Google for billing operations")
    auth_login.add_argument("--billing-url", default=None)
    auth_login.add_argument("--no-open", action="store_true")
    auth_login.add_argument("--timeout-seconds", type=int, default=180)
    auth_login.add_argument("--poll-seconds", type=int, default=2)
    auth_logout = auth_sub.add_parser("logout", help="Clear local auth session")
    auth_logout.add_argument("--billing-url", default=None)

    purchase = sub.add_parser("purchase", help="Create Solo purchase and wait for license provisioning")
    purchase.add_argument("--email", default="")
    purchase.add_argument("--plan", default=DEFAULT_PLAN)
    purchase.add_argument(
        "--mode",
        default=DEFAULT_PURCHASE_MODE,
        choices=["test", "live"],
        help="Checkout mode: live uses Stripe, test uses local dev checkout",
    )
    purchase.add_argument("--billing-url", default=None, help="Override billing API base URL")
    purchase.add_argument("--success-url", default=None, help=argparse.SUPPRESS)
    purchase.add_argument("--cancel-url", default=None, help=argparse.SUPPRESS)
    purchase.add_argument("--poll-seconds", type=int, default=3, help=argparse.SUPPRESS)
    purchase.add_argument("--timeout-seconds", type=int, default=300, help=argparse.SUPPRESS)
    purchase.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)
    purchase.add_argument("--non-interactive", action="store_true", help=argparse.SUPPRESS)
    purchase.add_argument("--preview", action="store_true", help=argparse.SUPPRESS)

    unsubscribe = sub.add_parser("unsubscribe", help="Open Stripe billing portal to cancel/manage subscription")
    unsubscribe.add_argument("--purchase-id", default="", help="Override purchase ID (otherwise inferred from local license)")
    unsubscribe.add_argument("--email", default="", help="Fallback email lookup if purchase ID is unavailable")
    unsubscribe.add_argument("--billing-url", default=None, help="Override billing API base URL")
    unsubscribe.add_argument("--return-url", default="", help="Optional return URL after leaving Stripe portal")
    unsubscribe.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)

    status = sub.add_parser("status", help="Show runtime tier, capabilities, and license details")
    status.add_argument("--json", action="store_true")
    status.add_argument("--remote-verify", action="store_true")
    status.add_argument("--license-url", default=None)

    entitlements = sub.add_parser("entitlements", help="Manage local entitlement token cache")
    entitlements_sub = entitlements.add_subparsers(dest="entitlement_action", required=False)

    ent_status = entitlements_sub.add_parser("status", help="Show entitlement cache and effective tier")
    ent_status.add_argument("--json", action="store_true")

    ent_activate = entitlements_sub.add_parser("activate", help="Save local entitlement token")
    ent_activate.add_argument("--token", default="")

    entitlements_sub.add_parser("clear", help="Remove cached entitlement token")

    ingest = sub.add_parser("ingest", help="Ingest PDFs into Solo knowledge store")
    ingest.add_argument("folder", help="Path to folder containing PDFs")
    ingest.add_argument("--project-name", "-n", default="")
    ingest.add_argument("--dpi", type=int, default=200)
    ingest.add_argument("--store", default=None)

    doctor = sub.add_parser("doctor", help="Validate and repair Solo runtime setup")
    doctor.add_argument("--fix", action="store_true")
    doctor.add_argument("--store", default=None)
    doctor.add_argument("--no-restart", action="store_true")
    doctor.add_argument("--field-access-required", action="store_true")
    doctor.add_argument("--json", action="store_true")

    up = sub.add_parser("up", help="Start Solo runtime (core by default, pro when entitled)")
    up.add_argument("--port", type=int, default=3000)
    up.add_argument("--host", type=str, default="0.0.0.0")
    up.add_argument("--store", type=str, default=None)
    up.add_argument("--tui", action="store_true")
    up.add_argument("--skip-doctor", action="store_true")
    up.add_argument("--no-fix", action="store_true")
    up.add_argument("--no-restart", action="store_true")
    up.add_argument("--field-access-required", action="store_true")
    up.add_argument("--require-pro", action="store_true")

    serve = sub.add_parser("serve", help=argparse.SUPPRESS)
    serve.add_argument("--port", type=int, default=3000)
    serve.add_argument("--host", type=str, default="0.0.0.0")
    serve.add_argument("--store", type=str, default=None)

    migrate = sub.add_parser("migrate-legacy", help="Import legacy Maestro Solo state into isolated Solo paths")
    migrate.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: list[str] | None = None):
    parsed_argv = list(argv) if argv is not None else None
    if parsed_argv and parsed_argv[0] == "install":
        parsed_argv[0] = "setup"

    args = build_parser().parse_args(parsed_argv)
    handlers = {
        "setup": _cmd_setup,
        "auth": _cmd_auth,
        "purchase": _cmd_purchase,
        "unsubscribe": _cmd_unsubscribe,
        "status": _cmd_status,
        "entitlements": _cmd_entitlements,
        "ingest": _cmd_ingest,
        "doctor": _cmd_doctor,
        "up": _cmd_up,
        "serve": _cmd_serve,
        "migrate-legacy": _cmd_migrate_legacy,
    }

    code = handlers[args.command](args)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
