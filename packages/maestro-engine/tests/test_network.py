from __future__ import annotations

from maestro_engine.network import resolve_network_urls


def test_resolve_network_urls_local_fallback_without_tailscale(monkeypatch):
    monkeypatch.setattr("maestro_engine.network.shutil.which", lambda _: None)

    payload = resolve_network_urls(web_port=3000, route_path="/workspace")

    assert payload["localhost_url"] == "http://localhost:3000/workspace"
    assert payload["tailnet_url"] is None
    assert payload["recommended_url"] == "http://localhost:3000/workspace"
