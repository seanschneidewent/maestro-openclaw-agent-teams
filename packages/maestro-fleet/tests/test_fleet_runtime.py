from __future__ import annotations

import json
from pathlib import Path

import maestro_fleet.runtime as runtime


def test_managed_listener_pids_supports_keyword_only_matcher() -> None:
    def _listener_pids(port: int) -> list[int]:
        assert port == 3000
        return [111, 222]

    def _matcher(pid: int, *, port: int | None = None, store_root: Path | None = None, host: str | None = None) -> bool:
        return pid == 222 and port == 3000 and host == "0.0.0.0" and store_root == Path("/tmp/store")

    matched = runtime.managed_listener_pids(
        port=3000,
        store_root=Path("/tmp/store"),
        host="0.0.0.0",
        listener_pids_fn=_listener_pids,
        is_fleet_server_process_fn=_matcher,
    )

    assert matched == [222]


def test_start_detached_server_tolerates_health_pending_process(monkeypatch, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store_root = tmp_path / "store"
    store_root.mkdir(parents=True, exist_ok=True)

    class _Proc:
        pid = 4242
        returncode = None

        def poll(self):
            return None

    def _fake_popen(*args, **kwargs):
        return _Proc()

    clock = {"now": 0.0}

    def _fake_time() -> float:
        return float(clock["now"])

    def _fake_sleep(seconds: float) -> None:
        clock["now"] += float(seconds)

    monkeypatch.setattr(runtime.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(runtime.time, "time", _fake_time)
    monkeypatch.setattr(runtime.time, "sleep", _fake_sleep)

    def _save_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    result = runtime.start_detached_server(
        port=3000,
        store_root=store_root,
        host="0.0.0.0",
        state_dir=state_dir,
        now_iso=lambda: "2026-03-09T16:00:00Z",
        load_json_fn=lambda path, default: default,
        save_json_fn=_save_json,
        pid_running_fn=lambda pid: False,
        terminate_process_fn=lambda pid: True,
        managed_listener_pids_fn=lambda port, store, host: [],
        listener_pids_fn=lambda port: [],
        is_fleet_server_process_fn=lambda pid, port=None, store_root=None, host=None: False,
        is_windows=False,
    )

    assert result["ok"] is True
    assert result["pid"] == 4242
    assert result["health_pending"] is True
    assert (state_dir / "serve.pid.json").exists()
    assert (state_dir / "serve.log").exists()

