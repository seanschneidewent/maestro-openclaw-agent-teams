"""Tests for customer help-pack installation helpers."""

from __future__ import annotations

import json
from pathlib import Path

from maestro import __version__
from maestro.help_pack import HELP_PACK_METADATA, bundled_fleet_help_pdfs, install_fleet_help_pack


def test_bundled_fleet_help_pdfs_exist():
    pdfs = bundled_fleet_help_pdfs()
    assert pdfs
    assert all(path.suffix == ".pdf" for path in pdfs)


def test_install_fleet_help_pack_copies_managed_pdfs_and_metadata(tmp_path: Path):
    target_dir = tmp_path / "Desktop" / "Maestro Fleet Help"

    installed_dir = install_fleet_help_pack(target_dir)

    assert installed_dir == target_dir
    expected_names = [path.name for path in bundled_fleet_help_pdfs()]
    assert [path.name for path in sorted(target_dir.glob("*.pdf"))] == expected_names

    metadata = json.loads((target_dir / HELP_PACK_METADATA).read_text(encoding="utf-8"))
    assert metadata["product"] == "maestro-fleet"
    assert metadata["version"] == __version__
    assert metadata["managed_files"] == expected_names


def test_install_fleet_help_pack_removes_stale_managed_files_only(tmp_path: Path):
    target_dir = tmp_path / "Desktop" / "Maestro Fleet Help"
    target_dir.mkdir(parents=True)

    stale_managed = target_dir / "99 - Old Managed Doc.pdf"
    stale_managed.write_bytes(b"old")
    user_file = target_dir / "Customer Notes.txt"
    user_file.write_text("keep me", encoding="utf-8")
    metadata = {
        "product": "maestro-fleet",
        "managed_files": ["99 - Old Managed Doc.pdf"],
    }
    (target_dir / HELP_PACK_METADATA).write_text(json.dumps(metadata), encoding="utf-8")

    install_fleet_help_pack(target_dir)

    assert not stale_managed.exists()
    assert user_file.read_text(encoding="utf-8") == "keep me"
