"""
Tests for Maestro license enforcement layer.
"""

import os
import tempfile
from pathlib import Path
import pytest

from maestro.license import (
    generate_company_key,
    generate_project_key,
    validate_company_key,
    validate_project_key,
    get_machine_id,
    generate_project_fingerprint,
    stamp_knowledge_store,
    verify_knowledge_store,
    LicenseError,
)
from maestro.tools import MaestroTools


class TestMachineFingerprinting:
    """Test machine ID and fingerprint generation."""

    def test_get_machine_id_returns_string(self):
        """Machine ID should be a non-empty string."""
        machine_id = get_machine_id()
        assert isinstance(machine_id, str)
        assert len(machine_id) > 0
        assert len(machine_id) == 16  # Should be 16 chars

    def test_get_machine_id_is_stable(self):
        """Machine ID should be consistent across calls."""
        id1 = get_machine_id()
        id2 = get_machine_id()
        assert id1 == id2

    def test_generate_project_fingerprint(self):
        """Fingerprint should be generated with correct structure."""
        fp = generate_project_fingerprint("test-project", "/path/to/store")
        
        assert "machine_id" in fp
        assert "project_slug" in fp
        assert "store_hash" in fp
        assert "fingerprint" in fp
        assert "fingerprint_data" in fp
        
        assert fp["project_slug"] == "test-project"
        assert len(fp["fingerprint"]) == 8
        assert len(fp["machine_id"]) == 16

    def test_fingerprint_is_stable(self):
        """Same inputs should produce same fingerprint."""
        fp1 = generate_project_fingerprint("my-project", "/some/path")
        fp2 = generate_project_fingerprint("my-project", "/some/path")
        
        assert fp1["fingerprint"] == fp2["fingerprint"]
        assert fp1["machine_id"] == fp2["machine_id"]

    def test_fingerprint_changes_with_path(self):
        """Different paths should produce different fingerprints."""
        fp1 = generate_project_fingerprint("project", "/path/one")
        fp2 = generate_project_fingerprint("project", "/path/two")
        
        assert fp1["fingerprint"] != fp2["fingerprint"]
        assert fp1["store_hash"] != fp2["store_hash"]

    def test_fingerprint_changes_with_slug(self):
        """Different slugs should produce different fingerprints."""
        fp1 = generate_project_fingerprint("project-a", "/path")
        fp2 = generate_project_fingerprint("project-b", "/path")
        
        assert fp1["fingerprint"] != fp2["fingerprint"]


class TestCompanyLicense:
    """Test company license key generation and validation."""

    def test_generate_company_key(self):
        """Should generate valid company key."""
        key = generate_company_key("CMP7F8A3D2E")
        
        assert key.startswith("MAESTRO-COMPANY-V1-")
        assert "CMP7F8A3D2E" in key
        parts = key.split("-")
        assert len(parts) == 6

    def test_validate_company_key(self):
        """Should validate a valid company key."""
        key = generate_company_key("CMPTEST1234")
        result = validate_company_key(key)
        
        assert result["type"] == "company"
        assert result["company_id"] == "CMPTEST1234"
        assert result["version"] == "V1"
        assert result["valid"] is True

    def test_validate_invalid_company_key_format(self):
        """Should reject malformed company keys."""
        with pytest.raises(LicenseError, match="Invalid company key format"):
            validate_company_key("MAESTRO-COMPANY-V1-INVALID")

    def test_validate_tampered_company_key(self):
        """Should reject company key with invalid signature."""
        key = generate_company_key("CMPTEST1234")
        # Tamper with the key
        tampered = key[:-4] + "XXXX"
        
        with pytest.raises(LicenseError, match="Invalid signature"):
            validate_company_key(tampered)

    def test_validate_wrong_prefix(self):
        """Should reject key with wrong prefix."""
        with pytest.raises(LicenseError, match="Invalid company key prefix"):
            validate_company_key("INVALID-COMPANY-V1-TEST-20260219-ABC123")


class TestProjectLicense:
    """Test project license key generation and validation."""

    def test_generate_project_key(self):
        """Should generate valid project key."""
        key = generate_project_key(
            "CMPTEST123",
            "PRJTEST456",
            "test-project",
            "/tmp/test_store",
        )
        
        assert key.startswith("MAESTRO-PROJECT-V1-")
        assert "CMPTEST123" in key
        assert "PRJTEST456" in key
        parts = key.split("-")
        assert len(parts) == 8

    def test_validate_project_key(self):
        """Should validate a valid project key."""
        project_slug = "test-project"
        store_path = "/tmp/test_store"
        
        key = generate_project_key(
            "CMPTEST123",
            "PRJTEST456",
            project_slug,
            store_path,
        )
        
        result = validate_project_key(key, project_slug, store_path)
        
        assert result["type"] == "project"
        assert result["company_id"] == "CMPTEST123"
        assert result["project_id"] == "PRJTEST456"
        assert result["version"] == "V1"
        assert result["valid"] is True

    def test_validate_project_key_fingerprint_mismatch(self):
        """Should reject project key with mismatched fingerprint."""
        key = generate_project_key(
            "CMPTEST123",
            "PRJTEST456",
            "original-project",
            "/tmp/original_path",
        )
        
        # Try to validate with different project/path
        with pytest.raises(LicenseError, match="fingerprint mismatch"):
            validate_project_key(key, "different-project", "/tmp/different_path")

    def test_validate_tampered_project_key(self):
        """Should reject project key with invalid signature."""
        key = generate_project_key(
            "CMPTEST123",
            "PRJTEST456",
            "test-project",
            "/tmp/test_store",
        )
        
        # Tamper with the signature
        tampered = key[:-4] + "XXXX"
        
        with pytest.raises(LicenseError, match="Invalid signature"):
            validate_project_key(tampered, "test-project", "/tmp/test_store")


class TestKnowledgeStoreStamping:
    """Test knowledge store license stamping and verification."""

    def test_stamp_and_verify_knowledge_store(self):
        """Should stamp and verify knowledge store successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "knowledge_store"
            store_path.mkdir()
            
            project_slug = "test-project"
            key = generate_project_key(
                "CMPTEST123",
                "PRJTEST456",
                project_slug,
                str(store_path),
            )
            
            # Stamp the knowledge store
            stamp_knowledge_store(str(store_path), key, project_slug)
            
            # Verify license.json was created
            license_file = store_path / "license.json"
            assert license_file.exists()
            
            # Verify the stamp
            result = verify_knowledge_store(str(store_path), key, project_slug)
            assert result is True

    def test_verify_missing_license_file(self):
        """Should fail if license.json is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "knowledge_store"
            store_path.mkdir()
            
            key = generate_project_key(
                "CMPTEST123",
                "PRJTEST456",
                "test-project",
                str(store_path),
            )
            
            with pytest.raises(LicenseError, match="not licensed"):
                verify_knowledge_store(str(store_path), key, "test-project")

    def test_verify_wrong_license_key(self):
        """Should fail if different license key is used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "knowledge_store"
            store_path.mkdir()
            
            project_slug = "test-project"
            key1 = generate_project_key("CMP1", "PRJ1", project_slug, str(store_path))
            key2 = generate_project_key("CMP2", "PRJ2", project_slug, str(store_path))
            
            # Stamp with key1
            stamp_knowledge_store(str(store_path), key1, project_slug)
            
            # Try to verify with key2
            with pytest.raises(LicenseError, match="different license"):
                verify_knowledge_store(str(store_path), key2, project_slug)

    def test_verify_moved_knowledge_store(self):
        """Should fail if knowledge store is moved to different path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = Path(tmpdir) / "original"
            original_path.mkdir()
            
            project_slug = "test-project"
            key = generate_project_key("CMP1", "PRJ1", project_slug, str(original_path))
            
            # Stamp at original path
            stamp_knowledge_store(str(original_path), key, project_slug)
            
            # Simulate move to different path
            new_path = Path(tmpdir) / "moved"
            original_path.rename(new_path)
            
            # Verification should fail (fingerprint includes path)
            with pytest.raises(LicenseError, match="fingerprint mismatch"):
                verify_knowledge_store(str(new_path), key, project_slug)


class TestLicenseDecorator:
    """Test @requires_license decorator on MaestroTools."""

    def test_tools_without_license(self):
        """Tools should be disabled without a valid license."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal project structure
            store_path = Path(tmpdir) / "knowledge_store"
            store_path.mkdir()
            project_dir = store_path / "test-project"
            project_dir.mkdir()
            
            # Create minimal project.json
            import json
            project_json = project_dir / "project.json"
            project_json.write_text(json.dumps({
                "name": "test-project",
                "slug": "test-project",
                "pages": {},
            }))
            
            # Initialize tools without license
            if "MAESTRO_LICENSE_KEY" in os.environ:
                old_key = os.environ["MAESTRO_LICENSE_KEY"]
                del os.environ["MAESTRO_LICENSE_KEY"]
            else:
                old_key = None
            
            try:
                tools = MaestroTools(store_path=str(store_path))
                assert tools.licensed is False
                
                # Tool methods should return error message
                result = tools.search("test")
                assert isinstance(result, str)
                assert "License required" in result
                
            finally:
                if old_key:
                    os.environ["MAESTRO_LICENSE_KEY"] = old_key

    def test_tools_with_valid_license(self):
        """Tools should work with a valid license."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "knowledge_store"
            store_path.mkdir()
            project_dir = store_path / "test-project"
            project_dir.mkdir()
            
            project_slug = "test-project"
            
            # Generate license using the store_path (not project_dir)
            # because MaestroTools uses store_path for validation
            key = generate_project_key("CMP1", "PRJ1", project_slug, str(store_path))
            
            # Create minimal project.json
            import json
            project_json = project_dir / "project.json"
            project_json.write_text(json.dumps({
                "name": project_slug,
                "slug": project_slug,
                "pages": {},
                "disciplines": [],
                "index": {"materials": {}, "keywords": {}},
            }))
            
            # Stamp the knowledge store using store_path
            stamp_knowledge_store(str(store_path), key, project_slug)
            
            # Set license in environment
            old_key = os.environ.get("MAESTRO_LICENSE_KEY")
            os.environ["MAESTRO_LICENSE_KEY"] = key
            
            try:
                tools = MaestroTools(store_path=str(store_path))
                assert tools.licensed is True
                
                # Tool methods should work (even if they return "no results")
                result = tools.search("test")
                # Should not return license error
                assert not isinstance(result, str) or "License required" not in result
                
            finally:
                if old_key:
                    os.environ["MAESTRO_LICENSE_KEY"] = old_key
                else:
                    del os.environ["MAESTRO_LICENSE_KEY"]

    def test_skip_license_check_for_testing(self):
        """Should be able to skip license check for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "knowledge_store"
            store_path.mkdir()
            project_dir = store_path / "test-project"
            project_dir.mkdir()
            
            # Create minimal project.json
            import json
            project_json = project_dir / "project.json"
            project_json.write_text(json.dumps({
                "name": "test-project",
                "slug": "test-project",
                "pages": {},
            }))
            
            # Initialize with skip_license_check=True
            tools = MaestroTools(
                store_path=str(store_path),
                skip_license_check=True,
            )
            
            # License check should be skipped, tools should work
            # (though they may return empty results)
            assert hasattr(tools, "search")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
