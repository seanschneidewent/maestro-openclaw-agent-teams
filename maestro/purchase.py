"""Compatibility wrapper for legacy Fleet project provisioning imports."""

from __future__ import annotations

from .fleet.projects.provisioning import *  # noqa: F401,F403
from .fleet.projects.provisioning import run_project_create


def run_purchase(*args, **kwargs):
    return run_project_create(*args, **kwargs)


def main(argv: list[str] | None = None):
    _ = argv
    from rich.console import Console

    console = Console()
    console.print(
        "[red]`maestro-purchase` is disabled in Fleet mode.[/]\n"
        "[bold white]Use:[/] `maestro-fleet project create`"
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
