"""Fleet-native server entrypoint for the Command Center runtime."""

from __future__ import annotations

import argparse

from .actions import install_fleet_action_runner
from .command_center import install_fleet_command_center_backend
from .doctor import build_doctor_report as build_fleet_doctor_report
from .openclaw_runtime import ensure_openclaw_profile_env
from .runtime import resolve_network_urls
from .state import resolve_fleet_store_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start Maestro Fleet web server")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--store", type=str, default=None, help="Override fleet store root")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    return parser


def main(argv: list[str] | None = None):
    ensure_openclaw_profile_env()

    parser = build_parser()
    args = parser.parse_args(argv)
    resolved_store = resolve_fleet_store_root(args.store)

    try:
        from maestro.server import app
        import maestro.server as srv
        import uvicorn
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "maestro-fleet server currently depends on legacy runtime modules in `maestro/`.\n"
            "Install root package too: pip install -e /absolute/path/to/repo"
        ) from exc

    install_fleet_command_center_backend(srv)
    install_fleet_action_runner(srv)
    srv.build_doctor_report = build_fleet_doctor_report
    srv.store_path = resolved_store
    srv.server_port = int(args.port)
    network = resolve_network_urls(web_port=int(args.port), route_path="/command-center")
    print(f"Maestro Fleet server starting on http://localhost:{args.port}")
    print(f"Knowledge store: {srv.store_path}")
    print(f"Command Center (local): {network.get('localhost_url')}")
    tailnet_url = network.get("tailnet_url")
    if tailnet_url:
        print(f"Command Center (tailnet): {tailnet_url}")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    raise SystemExit(main())
