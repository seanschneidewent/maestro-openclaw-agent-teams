from __future__ import annotations

from pathlib import Path

from maestro_solo.doctor import _render_workspace_awareness_md, _sync_workspace_awareness_md


def test_render_workspace_awareness_prefers_tailnet_url():
    rendered = _render_workspace_awareness_md(
        model="openai-codex/gpt-5.2",
        preferred_url="http://100.74.19.112:3000/workspace",
        local_url="http://localhost:3000/workspace",
        tailnet_url="http://100.74.19.112:3000/workspace",
        store_root=Path("/tmp/store"),
        pending_optional_setup=["ingest_plans"],
        field_access_required=False,
    )

    assert "Recommended Workspace URL: `http://100.74.19.112:3000/workspace`" in rendered
    assert "Tailnet Workspace URL: `http://100.74.19.112:3000/workspace`" in rendered
    assert "Field Access Status: `ready`" in rendered


def test_sync_workspace_awareness_writes_file_when_fix_enabled(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    check = _sync_workspace_awareness_md(
        workspace,
        model="openai-codex/gpt-5.2",
        preferred_url="http://100.74.19.112:3000/workspace",
        local_url="http://localhost:3000/workspace",
        tailnet_url="http://100.74.19.112:3000/workspace",
        store_root=tmp_path / "store",
        pending_optional_setup=["tailscale", "ingest_plans"],
        field_access_required=False,
        fix=True,
    )

    assert check.ok is True
    assert check.fixed is True
    awareness = (workspace / "AWARENESS.md").read_text(encoding="utf-8")
    assert "Recommended Workspace URL: `http://100.74.19.112:3000/workspace`" in awareness
    assert "Pending Optional Setup: `tailscale, ingest_plans`" in awareness
