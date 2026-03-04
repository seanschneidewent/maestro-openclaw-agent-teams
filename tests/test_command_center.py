"""Tests for command center aggregation and APIs."""

from __future__ import annotations

import asyncio
import calendar
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import maestro.server as server
from maestro.command_center import (
    build_command_center_state,
    build_project_detail,
    build_project_snapshot,
    compute_attention_score,
    discover_project_dirs,
)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_project_store(root: Path, name: str, strong_risk: bool = True):
    project = root
    _write_json(
        project / "project.json",
        {
            "name": name,
            "total_pages": 197,
            "index_summary": {"pointer_count": 1428},
            "ingested_at": "2026-02-18T00:29:39",
        },
    )
    _write_json(project / "index.json", {"summary": {"page_count": 197, "pointer_count": 1428}})

    _write_json(
        project / "schedule" / "current_update.json",
        {
            "data_date": "2026-02-21",
            "percent_complete": 22,
            "schedule_performance_index": 0.95 if strong_risk else 1.02,
            "weather_delays": 2 if strong_risk else 0,
            "activity_updates": [
                {"id": "A3030", "variance_days": 3 if strong_risk else 0},
                {"id": "A3040", "variance_days": 4 if strong_risk else 0},
            ],
            "critical_path_activities": ["A3030", "A3040", "A3050"],
            "upcoming_critical_activities": [
                {
                    "id": "A3030",
                    "name": "Underground Utilities - Storm",
                    "blockers": ["RFI #12 - catch basin"],
                }
            ],
            "variance_notes": "3 days behind baseline",
        },
    )
    _write_json(
        project / "schedule" / "lookahead.json",
        {
            "generated": "2026-02-21T08:00:00",
            "constraints": [
                {
                    "activity_id": "A3030",
                    "description": "RFI #12 response needed by 2/26",
                    "impact_if_delayed": "3 additional days on critical path",
                },
                {
                    "activity_id": "A3050",
                    "description": "Submittal #14 needs approval",
                    "impact_if_delayed": "Cannot install sanitary sewer",
                },
            ],
            "material_deliveries": [],
            "inspections_required": [],
        },
    )
    _write_json(project / "schedule" / "baseline.json", {"contract_duration_days": 120})

    _write_json(
        project / "rfis" / "log.json",
        {
            "total_rfis": 18,
            "status_summary": {"open": 5},
            "rfis": [
                {
                    "id": "RFI-012",
                    "status": "Open",
                    "days_outstanding": 18,
                    "blocking_activity": True,
                    "risk_level": "High",
                    "subject": "Storm Catch Basin Depth",
                },
                {"id": "RFI-013", "status": "Closed"},
            ],
        },
    )

    _write_json(
        project / "submittals" / "log.json",
        {
            "total_submittals": 28,
            "status_summary": {
                "pending_review": 6,
                "rejected": 2 if strong_risk else 0,
            },
            "submittals": [
                {
                    "id": "SUB-014",
                    "status": "Pending Review",
                    "risk_level": "High",
                    "lead_time_weeks": 6,
                    "description": "Manhole Frames and Covers",
                },
                {
                    "id": "SUB-015",
                    "status": "Rejected - Resubmit Required" if strong_risk else "Approved",
                    "description": "Grease Interceptor",
                },
            ],
        },
    )

    _write_json(
        project / "comms" / "decisions.json",
        {
            "summary": {
                "total_decisions": 10,
                "pending_change_orders": 2 if strong_risk else 0,
                "total_exposure": 1330 if strong_risk else 0,
                "exposure_risks": [
                    {
                        "decision_id": "DEC-005",
                        "description": "Menu board relocation",
                        "exposure_amount": 750,
                    }
                ],
            }
        },
    )

    _write_json(
        project / "contracts" / "scope_matrix.json",
        {
            "identified_gaps": [{"work_item": "Low-voltage systems"}] if strong_risk else [],
            "identified_overlaps": [{"work_item": "Dumpster pad lighting"}],
        },
    )


def _project_slug_from_state(state_payload: dict, project_store_root: Path) -> str:
    expected = build_project_snapshot(project_store_root)["slug"]
    projects = state_payload.get("projects", []) if isinstance(state_payload, dict) else []
    assert any(isinstance(item, dict) and item.get("slug") == expected for item in projects)
    return expected


@pytest.fixture
def single_project_store(tmp_path: Path):
    _make_project_store(tmp_path, "Chick-fil-A Love Field FSU 03904 -CPS", strong_risk=True)
    return tmp_path


@pytest.fixture
def multi_project_store(tmp_path: Path):
    p1 = tmp_path / "Project One"
    p2 = tmp_path / "Project Two"
    _make_project_store(p1, "Project One", strong_risk=True)
    _make_project_store(p2, "Project Two", strong_risk=False)
    return tmp_path


class TestCommandCenterAggregation:
    def test_discover_project_dirs_single_root(self, single_project_store: Path):
        dirs = discover_project_dirs(single_project_store)
        assert len(dirs) == 1
        assert dirs[0] == single_project_store

    def test_discover_project_dirs_multi_root(self, multi_project_store: Path):
        dirs = discover_project_dirs(multi_project_store)
        assert len(dirs) == 2
        names = sorted(d.name for d in dirs)
        assert names == ["Project One", "Project Two"]

    def test_build_project_snapshot_metrics(self, single_project_store: Path):
        snapshot = build_project_snapshot(single_project_store)
        assert snapshot["name"].startswith("Chick-fil-A Love Field")
        assert snapshot["rfis"]["open"] == 5
        assert snapshot["submittals"]["pending_review"] == 6
        assert snapshot["decisions"]["total_exposure_usd"] == 1330
        assert snapshot["scope_risk"]["gaps"] == 1
        assert snapshot["attention_score"] == 100

    def test_build_command_center_state(self, multi_project_store: Path):
        state = build_command_center_state(multi_project_store)
        assert "projects" in state
        assert len(state["projects"]) == 2
        assert state["projects"][0]["attention_score"] >= state["projects"][1]["attention_score"]
        assert state["orchestrator"]["name"] == "The Commander"

    def test_compute_attention_score_formula(self):
        score = compute_attention_score(
            {
                "health": {
                    "schedule_performance_index": 0.95,
                    "variance_days": -3,
                    "weather_delays": 2,
                },
                "rfis": {"blocking_open": 1},
                "submittals": {"rejected": 1},
                "decisions": {"pending_change_orders": 1},
                "scope_risk": {"gaps": 1},
            }
        )
        assert score == 100

    def test_build_project_detail_drawers(self, single_project_store: Path):
        detail = build_project_detail(single_project_store)
        assert "snapshot" in detail
        assert "drawers" in detail
        assert "operational_health" in detail["drawers"]
        assert "critical_path" in detail["drawers"]

    def test_command_center_state_uses_active_system_directives(self, single_project_store: Path):
        _write_json(
            single_project_store / ".command_center" / "system_directives.json",
            {
                "version": 1,
                "updated_at": "2026-02-22T00:00:00Z",
                "directives": [
                    {
                        "id": "DIR-ACTIVE",
                        "title": "Active directive",
                        "body": "Use project maestro for plan detail",
                        "status": "active",
                        "scope": "global",
                        "priority": 90,
                    },
                    {
                        "id": "DIR-DRAFT",
                        "title": "Draft directive",
                        "body": "Draft content",
                        "status": "draft",
                        "scope": "global",
                        "priority": 100,
                    },
                ],
            },
        )
        state = build_command_center_state(single_project_store)
        assert len(state["directives"]) == 1
        assert state["directives"][0]["id"] == "DIR-ACTIVE"

    def test_snapshot_uses_fresh_heartbeat_overlay(self, single_project_store: Path):
        _write_json(
            single_project_store / ".command_center" / "heartbeat.json",
            {
                "version": 1,
                "agent_id": "maestro-project-chick-fil-a-love-field-fsu-03904-cps",
                "project_slug": "chick-fil-a-love-field-fsu-03904-cps",
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "loop_state": "computing",
                "summary": "Heartbeat summary",
                "top_risks": ["RFI-012 blocking podium"],
                "next_actions": ["Escalate RFI-012"],
                "confidence": 0.77,
                "pending_questions": 1,
            },
        )
        snapshot = build_project_snapshot(single_project_store)
        assert snapshot["heartbeat"]["available"] is True
        assert snapshot["heartbeat"]["is_fresh"] is True
        assert snapshot["status_report"]["source"] == "heartbeat"
        assert snapshot["status_report"]["summary"] == "Heartbeat summary"


class TestCommandCenterAPI:
    def test_state_endpoint_function(self, single_project_store: Path):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()

        payload = asyncio.run(server.api_command_center_state())
        assert "projects" in payload
        assert any(project.get("slug") == build_project_snapshot(single_project_store)["slug"] for project in payload["projects"])

    def test_project_detail_endpoint_function(self, single_project_store: Path):
        server.store_path = single_project_store
        payload = asyncio.run(server.api_command_center_state())
        slug = payload["projects"][0]["slug"]

        detail = asyncio.run(server.api_command_center_project_detail(slug))
        assert "snapshot" in detail
        assert detail["snapshot"]["slug"] == slug

    def test_project_detail_endpoint_not_found(self, single_project_store: Path):
        server.store_path = single_project_store
        response = asyncio.run(server.api_command_center_project_detail("missing-project"))
        assert isinstance(response, JSONResponse)
        assert response.status_code == 404

    def test_node_status_endpoint_function(self, single_project_store: Path):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()
        state = asyncio.run(server.api_command_center_state())
        slug = _project_slug_from_state(state, single_project_store)

        payload = asyncio.run(server.api_command_center_node_status(slug))
        assert payload["ok"] is True
        assert payload["project_slug"] == slug
        assert "status_report" in payload
        assert "online_state" in payload

    def test_commander_node_status_endpoint(self, single_project_store: Path):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()

        payload = asyncio.run(server.api_command_center_node_status("commander"))
        assert payload["ok"] is True
        assert payload["project_slug"] == "commander"
        assert payload["agent_id"] == "maestro-company"
        assert payload["online_state"] in {"online", "offline"}

    def test_node_conversation_endpoint_function(self, single_project_store: Path, monkeypatch):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()
        state = asyncio.run(server.api_command_center_state())
        slug = _project_slug_from_state(state, single_project_store)

        monkeypatch.setattr(
            server,
            "read_agent_conversation",
            lambda agent_id, **kwargs: {
                "ok": True,
                "agent_id": agent_id,
                "project_slug": kwargs.get("project_slug", ""),
                "session_id": "agent-session",
                "messages": [{"id": "u1", "timestamp": "2026-02-22T00:00:00Z", "role": "user", "text": "hello"}],
                "has_more": False,
                "source": "openclaw_sessions",
            },
        )

        payload = asyncio.run(server.api_command_center_node_conversation(slug, limit=25))
        assert payload["ok"] is True
        assert payload["project_slug"] == slug
        assert payload["messages"][0]["text"] == "hello"

    def test_commander_conversation_endpoint_function(self, single_project_store: Path, monkeypatch):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()

        monkeypatch.setattr(
            server,
            "read_agent_conversation",
            lambda agent_id, **kwargs: {
                "ok": True,
                "agent_id": agent_id,
                "project_slug": kwargs.get("project_slug", ""),
                "session_id": "agent-session",
                "messages": [{"id": "u1", "timestamp": "2026-02-22T00:00:00Z", "role": "user", "text": "commander ping"}],
                "has_more": False,
                "source": "openclaw_sessions",
            },
        )

        payload = asyncio.run(server.api_command_center_node_conversation("commander", limit=25))
        assert payload["ok"] is True
        assert payload["project_slug"] == "commander"
        assert payload["agent_id"] == "maestro-company"

    def test_node_send_endpoint_requires_manual_source(self, single_project_store: Path):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()
        response = asyncio.run(server.api_command_center_node_send("commander", {"message": "test", "source": "api"}))
        assert isinstance(response, JSONResponse)
        assert response.status_code == 400

    def test_node_send_endpoint_rejects_non_commander_nodes(self, single_project_store: Path):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()
        state = asyncio.run(server.api_command_center_state())
        slug = _project_slug_from_state(state, single_project_store)

        response = asyncio.run(server.api_command_center_node_send(
            slug,
            {"message": "status report", "source": "command_center_ui"},
        ))
        assert isinstance(response, JSONResponse)
        assert response.status_code == 403

    def test_node_send_endpoint_function(self, single_project_store: Path, monkeypatch):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()

        monkeypatch.setattr(
            server,
            "send_agent_message",
            lambda **kwargs: {
                "ok": True,
                "conversation": {
                    "ok": True,
                    "agent_id": kwargs["agent_id"],
                    "project_slug": kwargs.get("project_slug", ""),
                    "session_id": "agent-session",
                    "messages": [
                        {
                            "id": "a1",
                            "timestamp": "2026-02-22T00:00:00Z",
                            "role": "assistant",
                            "text": "ack",
                            "agent_id": kwargs["agent_id"],
                            "project_slug": kwargs.get("project_slug", ""),
                        }
                    ],
                },
                "result": {"ok": True},
            },
        )

        payload = asyncio.run(server.api_command_center_node_send(
            "commander",
            {"message": "status report", "source": "command_center_ui"},
        ))
        assert payload["ok"] is True
        assert payload["project_slug"] == "commander"
        assert payload["agent_id"] == "maestro-company"

    def test_registry_identity_overlays_assignee_in_state_and_detail(self, single_project_store: Path):
        slug = build_project_snapshot(single_project_store)["slug"]
        _write_json(
            single_project_store / ".command_center" / "fleet_registry.json",
            {
                "version": 1,
                "updated_at": "2026-02-21T00:00:00Z",
                "store_root": str(single_project_store),
                "projects": [
                    {
                        "project_slug": slug,
                        "project_name": "Chick-fil-A Love Field FSU 03904 -CPS",
                        "project_dir_name": single_project_store.name,
                        "project_store_path": str(single_project_store),
                        "maestro_agent_id": f"maestro-project-{slug}",
                        "ingest_input_root": "",
                        "superintendent": "Unknown",
                        "assignee": "andy",
                        "status": "active",
                        "last_ingest_at": "",
                        "last_index_at": "",
                        "last_updated": "",
                    }
                ],
            },
        )

        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()

        state_payload = asyncio.run(server.api_command_center_state())
        assert state_payload["projects"][0]["assignee"] == "andy"
        assert state_payload["projects"][0]["superintendent"] == "andy"

        detail_payload = asyncio.run(server.api_command_center_project_detail(slug))
        assert detail_payload["snapshot"]["assignee"] == "andy"
        assert detail_payload["snapshot"]["superintendent"] == "andy"

    def test_command_center_websocket_init(self, single_project_store: Path, monkeypatch):
        async def noop_watch():
            return

        monkeypatch.setattr(server, "watch_knowledge_store", noop_watch)
        monkeypatch.setattr(server, "profile_fleet_enabled", lambda: True)
        server.store_path = single_project_store

        with TestClient(server.app) as client:
            with client.websocket_connect("/ws/command-center") as ws:
                payload = ws.receive_json()
                assert payload["type"] == "command_center_init"
                assert any(
                    project.get("slug") == build_project_snapshot(single_project_store)["slug"]
                    for project in payload["state"]["projects"]
                    if isinstance(project, dict)
                )

    def test_agent_scoped_workspace_api_routes(self, single_project_store: Path):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()

        state = asyncio.run(server.api_command_center_state())
        slug = _project_slug_from_state(state, single_project_store)
        agent_id = f"maestro-project-{slug}"

        agents = asyncio.run(server.api_agent_workspace_index())
        assert "agents" in agents
        assert any(item["agent_id"] == agent_id for item in agents["agents"])

        project_payload = asyncio.run(server.api_agent_project(agent_id))
        assert project_payload["slug"] == slug
        assert project_payload["routes"]["agent_id"] == agent_id

    def test_agent_scoped_workspace_api_not_found(self, single_project_store: Path):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()

        missing = asyncio.run(server.api_agent_project("maestro-project-missing"))
        assert isinstance(missing, JSONResponse)
        assert missing.status_code == 404

    def test_workspace_schedule_status_endpoints(self, single_project_store: Path):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()
        state = asyncio.run(server.api_command_center_state())
        slug = _project_slug_from_state(state, single_project_store)
        agent_id = f"maestro-project-{slug}"

        schedule_status = asyncio.run(server.api_schedule_status(slug))
        assert schedule_status["files"]["current_update"] is True
        assert schedule_status["current"]["percent_complete"] == 22

        agent_status = asyncio.run(server.api_agent_schedule_status(agent_id))
        assert agent_status["current"]["percent_complete"] == 22

        timeline = asyncio.run(server.api_schedule_timeline(slug))
        expected_days = calendar.monthrange(int(timeline["month"][:4]), int(timeline["month"][5:7]))[1]
        assert timeline["week_starts_on"] == "monday"
        assert timeline["month"] == timeline["today"][:7]
        assert timeline["include_empty_days"] is True
        assert timeline["day_count"] == expected_days
        assert isinstance(timeline["days"], list)
        assert any(day.get("is_today") for day in timeline["days"])

        agent_timeline = asyncio.run(server.api_agent_schedule_timeline(agent_id))
        assert agent_timeline["today"] == timeline["today"]

    def test_workspace_schedule_item_crud_endpoints(self, single_project_store: Path):
        server.store_path = single_project_store
        server.load_all_projects()
        server._refresh_command_center_state()
        server._refresh_control_plane_state()
        state = asyncio.run(server.api_command_center_state())
        slug = _project_slug_from_state(state, single_project_store)
        agent_id = f"maestro-project-{slug}"

        created = asyncio.run(server.api_schedule_upsert_item(
            slug,
            {
                "item_id": "milestone_podium_pour",
                "title": "Podium pour",
                "type": "milestone",
                "status": "pending",
                "due_date": "2026-03-01",
                "owner": "andy",
            },
        ))
        assert created["status"] == "created"
        assert created["item"]["id"] == "milestone_podium_pour"

        updated = asyncio.run(server.api_schedule_upsert_item(
            slug,
            {
                "item_id": "milestone_podium_pour",
                "description": "Field-ready pour milestone",
                "date": "2026-03-02",
            },
        ))
        assert updated["status"] == "updated"
        assert updated["item"]["description"] == "Field-ready pour milestone"
        assert updated["item"]["due_date"] == "2026-03-02"

        listed = asyncio.run(server.api_schedule_items(slug))
        assert listed["count"] >= 1
        assert any(item["id"] == "milestone_podium_pour" for item in listed["items"])

        march_timeline = asyncio.run(server.api_schedule_timeline(slug, month="2026-03", include_empty_days=True))
        assert march_timeline["month"] == "2026-03"
        assert march_timeline["day_count"] == 31
        march_day = next(item for item in march_timeline["days"] if item["date"] == "2026-03-02")
        assert any(item["id"] == "milestone_podium_pour" for item in march_day["items"])

        closed = asyncio.run(server.api_agent_schedule_close_item(
            agent_id,
            "milestone_podium_pour",
            {"status": "done", "reason": "Closed by test"},
        ))
        assert closed["status"] == "closed"
        assert closed["item"]["status"] == "done"

    def test_state_includes_non_project_agents_from_openclaw_config(self, single_project_store: Path, monkeypatch):
        server.store_path = single_project_store
        server.load_all_projects()
        monkeypatch.setattr(
            server,
            "_load_openclaw_config_for_command_center",
            lambda: {
                "agents": {
                    "list": [
                        {"id": "maestro-company", "name": "The Commander", "default": True},
                        {"id": "specialist-weather", "name": "Weather Specialist", "default": False},
                    ]
                }
            },
        )
        server._refresh_command_center_state()
        server._refresh_control_plane_state()

        payload = asyncio.run(server.api_command_center_state())
        specialist = next(
            (item for item in payload["projects"] if isinstance(item, dict) and item.get("agent_id") == "specialist-weather"),
            None,
        )
        assert isinstance(specialist, dict)
        assert specialist["node_type"] == "specialist"

    def test_specialist_node_conversation_uses_agent_id(self, single_project_store: Path, monkeypatch):
        server.store_path = single_project_store
        server.load_all_projects()
        monkeypatch.setattr(
            server,
            "_load_openclaw_config_for_command_center",
            lambda: {
                "agents": {
                    "list": [
                        {"id": "maestro-company", "name": "The Commander", "default": True},
                        {"id": "specialist-weather", "name": "Weather Specialist", "default": False},
                    ]
                }
            },
        )
        seen: dict[str, str] = {}

        def _fake_read(agent_id, **kwargs):
            seen["agent_id"] = str(agent_id)
            seen["project_slug"] = str(kwargs.get("project_slug", ""))
            return {
                "ok": True,
                "agent_id": agent_id,
                "project_slug": kwargs.get("project_slug", ""),
                "messages": [],
                "has_more": False,
            }

        monkeypatch.setattr(server, "read_agent_conversation", _fake_read)
        server._refresh_command_center_state()
        server._refresh_control_plane_state()

        payload = asyncio.run(server.api_command_center_state())
        specialist = next(
            (item for item in payload["projects"] if isinstance(item, dict) and item.get("agent_id") == "specialist-weather"),
            None,
        )
        assert isinstance(specialist, dict)
        slug = str(specialist.get("slug", ""))
        assert slug

        convo = asyncio.run(server.api_command_center_node_conversation(slug, limit=10))
        assert convo["ok"] is True
        assert seen["agent_id"] == "specialist-weather"
        assert seen["project_slug"] == ""
