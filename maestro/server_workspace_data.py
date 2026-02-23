"""Workspace data helpers for workspace API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import load_json


def workspaces_dir(proj: dict[str, Any]) -> Path:
    ws_dir = Path(proj["path"]) / "workspaces"
    ws_dir.mkdir(parents=True, exist_ok=True)
    return ws_dir


def load_workspace(proj: dict[str, Any], ws_slug: str) -> dict[str, Any] | None:
    ws_path = workspaces_dir(proj) / ws_slug / "workspace.json"
    data = load_json(ws_path)
    return data if isinstance(data, dict) else None


def load_all_workspaces(proj: dict[str, Any]) -> list[dict[str, Any]]:
    ws_dir = workspaces_dir(proj)
    workspaces: list[dict[str, Any]] = []
    for d in sorted(ws_dir.iterdir(), key=lambda p: p.name.lower()) if ws_dir.exists() else []:
        if d.is_dir():
            ws = load_workspace(proj, d.name)
            if ws:
                workspaces.append(ws)
    return workspaces


def get_page_bboxes(proj: dict[str, Any], page_name: str, pointer_ids: list[str]) -> list[dict[str, Any]]:
    page = proj.get("pages", {}).get(page_name, {})
    regions = page.get("regions", [])
    bboxes: list[dict[str, Any]] = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        if region.get("id") in pointer_ids:
            bboxes.append(
                {
                    "id": region["id"],
                    "label": region.get("label", ""),
                    "type": region.get("type", ""),
                    "bbox": region.get("bbox", {}),
                }
            )
    return bboxes
