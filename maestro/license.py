"""
Maestro License System — local cryptographic validation for two-tier licensing.

Company licenses: free tier for company-level agent
Project licenses: paid tier bound to machine fingerprint + project

Uses HMAC-SHA256 signatures for verification.
No external payment backend — just local validation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Constants ─────────────────────────────────────────────────────────────────

# Hardcoded test secret for local validation
MAESTRO_SECRET = "MAESTRO_TEST_SECRET_2026"


class LicenseError(Exception):
    """License validation failure."""
    pass


# ── Machine Fingerprinting ────────────────────────────────────────────────────

def get_machine_id() -> str:
    """
    Get stable machine identifier.
    
    Returns:
        Unique machine ID string (16 characters)
    """
    system = platform.system()
    
    try:
        if system == "Windows":
            # Use Windows machine GUID
            result = subprocess.run(
                ["wmic", "csproduct", "get", "UUID"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                machine_id = lines[1].strip()
                if machine_id and machine_id != "":
                    return hashlib.sha256(machine_id.encode()).hexdigest()[:16]
        
        elif system == "Linux":
            # Use /etc/machine-id
            for path in [Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")]:
                if path.exists():
                    return path.read_text().strip()[:16]
        
        elif system == "Darwin":
            # Use macOS IOPlatformUUID
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "IOPlatformUUID" in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        uuid_str = parts[3]
                        return hashlib.sha256(uuid_str.encode()).hexdigest()[:16]
    
    except Exception:
        pass
    
    # Fallback: hash MAC address
    mac = uuid.getnode()
    return hashlib.sha256(str(mac).encode()).hexdigest()[:16]


def generate_project_fingerprint(project_slug: str, knowledge_store_path: str) -> dict[str, str]:
    """
    Generate fingerprint for project license binding.
    
    Combines:
      - machine_id: stable hardware identifier
      - project_slug: normalized project name
      - store_hash: SHA256 of knowledge store absolute path
    
    Args:
        project_slug: Project slug (e.g., "chick-fil-a-love-field")
        knowledge_store_path: Path to knowledge store directory
    
    Returns:
        Dict with machine_id, project_slug, store_hash, fingerprint, fingerprint_data
    """
    machine_id = get_machine_id()
    
    store_path = Path(knowledge_store_path).resolve()
    store_hash = hashlib.sha256(str(store_path).encode()).hexdigest()[:16]
    
    fingerprint_data = f"{machine_id}:{project_slug}:{store_hash}"
    fingerprint = hashlib.sha256(fingerprint_data.encode()).hexdigest()[:8]
    
    return {
        "machine_id": machine_id,
        "project_slug": project_slug,
        "store_hash": store_hash,
        "fingerprint": fingerprint.upper(),
        "fingerprint_data": fingerprint_data,
    }


# ── Company License ───────────────────────────────────────────────────────────

def generate_company_key(company_id: str) -> str:
    """
    Generate a Company Maestro license key.
    
    Format: MAESTRO-COMPANY-V1-{COMPANY_ID}-{TIMESTAMP}-{SIGNATURE}
    
    Args:
        company_id: Unique company identifier (e.g., "CMP7F8A3D2E")
    
    Returns:
        Full license key string
    """
    version = "V1"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    
    payload = f"MAESTRO-COMPANY-{version}-{company_id}-{timestamp}"
    signature = hmac.new(
        MAESTRO_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:12].upper()
    
    return f"MAESTRO-COMPANY-{version}-{company_id}-{timestamp}-{signature}"


def validate_company_key(key: str) -> dict[str, Any]:
    """
    Validate a Company Maestro license key.
    
    Args:
        key: Company license key string
    
    Returns:
        Dict with parsed key components
    
    Raises:
        LicenseError: If key is invalid
    """
    parts = key.split("-")
    
    if len(parts) != 6:
        raise LicenseError(f"Invalid company key format (expected 6 parts, got {len(parts)})")
    
    if parts[0] != "MAESTRO" or parts[1] != "COMPANY":
        raise LicenseError("Invalid company key prefix")
    
    version = parts[2]
    company_id = parts[3]
    timestamp = parts[4]
    provided_sig = parts[5]
    
    # Verify signature
    payload = f"MAESTRO-COMPANY-{version}-{company_id}-{timestamp}"
    expected_sig = hmac.new(
        MAESTRO_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:12].upper()
    
    if provided_sig != expected_sig:
        raise LicenseError("Invalid signature — key has been tampered with")
    
    return {
        "type": "company",
        "version": version,
        "company_id": company_id,
        "timestamp": timestamp,
        "valid": True,
    }


# ── Project License ───────────────────────────────────────────────────────────

def generate_project_key(
    company_id: str,
    project_id: str,
    project_slug: str,
    knowledge_store_path: str,
) -> str:
    """
    Generate a Project Maestro license key with machine fingerprint.
    
    Format: MAESTRO-PROJECT-V1-{COMPANY_ID}-{PROJECT_ID}-{TIMESTAMP}-{FINGERPRINT}-{SIGNATURE}
    
    Args:
        company_id: Parent company ID
        project_id: Unique project identifier (e.g., "PRJ4B2C9A1F")
        project_slug: Project slug for fingerprinting
        knowledge_store_path: Knowledge store path for fingerprinting
    
    Returns:
        Full license key string
    """
    version = "V1"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    
    fingerprint_data = generate_project_fingerprint(project_slug, knowledge_store_path)
    fingerprint = fingerprint_data["fingerprint"]
    
    payload = f"MAESTRO-PROJECT-{version}-{company_id}-{project_id}-{timestamp}-{fingerprint}"
    signature = hmac.new(
        MAESTRO_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:12].upper()
    
    return f"MAESTRO-PROJECT-{version}-{company_id}-{project_id}-{timestamp}-{fingerprint}-{signature}"


def validate_project_key(
    key: str,
    project_slug: str,
    knowledge_store_path: str,
) -> dict[str, Any]:
    """
    Validate a Project Maestro license key and verify fingerprint.
    
    Args:
        key: Project license key string
        project_slug: Current project slug
        knowledge_store_path: Current knowledge store path
    
    Returns:
        Dict with parsed key components
    
    Raises:
        LicenseError: If key is invalid or fingerprint doesn't match
    """
    parts = key.split("-")
    
    if len(parts) != 8:
        raise LicenseError(f"Invalid project key format (expected 8 parts, got {len(parts)})")
    
    if parts[0] != "MAESTRO" or parts[1] != "PROJECT":
        raise LicenseError("Invalid project key prefix")
    
    version = parts[2]
    company_id = parts[3]
    project_id = parts[4]
    timestamp = parts[5]
    key_fingerprint = parts[6]
    provided_sig = parts[7]
    
    # Verify signature
    payload = f"MAESTRO-PROJECT-{version}-{company_id}-{project_id}-{timestamp}-{key_fingerprint}"
    expected_sig = hmac.new(
        MAESTRO_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:12].upper()
    
    if provided_sig != expected_sig:
        raise LicenseError("Invalid signature — key has been tampered with")
    
    # Generate current fingerprint
    current_fp = generate_project_fingerprint(project_slug, knowledge_store_path)
    
    # Verify fingerprint matches
    if current_fp["fingerprint"] != key_fingerprint:
        raise LicenseError(
            f"License fingerprint mismatch.\n"
            f"This license is bound to different hardware or knowledge store location.\n"
            f"Expected: {key_fingerprint}\n"
            f"Current:  {current_fp['fingerprint']}\n"
            f"Machine:  {current_fp['machine_id']}\n"
            f"Store:    {knowledge_store_path}"
        )
    
    return {
        "type": "project",
        "version": version,
        "company_id": company_id,
        "project_id": project_id,
        "timestamp": timestamp,
        "fingerprint": key_fingerprint,
        "fingerprint_data": current_fp,
        "valid": True,
    }


# ── Knowledge Store Stamping ──────────────────────────────────────────────────

def stamp_knowledge_store(
    knowledge_store_path: str,
    license_key: str,
    project_slug: str,
) -> None:
    """
    Stamp a knowledge store with license metadata.
    
    Creates license.json in the knowledge store root with:
      - License key hash (for verification)
      - Fingerprint (machine + project binding)
      - Timestamp
      - Machine ID
    
    Args:
        knowledge_store_path: Path to knowledge store
        license_key: Project license key
        project_slug: Project slug
    """
    store_path = Path(knowledge_store_path)
    if not store_path.exists():
        raise FileNotFoundError(f"Knowledge store not found: {knowledge_store_path}")
    
    # Validate the license key first
    validation = validate_project_key(license_key, project_slug, str(store_path))
    
    # Create license stamp
    license_data = {
        "license_key_hash": hashlib.sha256(license_key.encode()).hexdigest(),
        "fingerprint": validation["fingerprint"],
        "fingerprint_data": validation["fingerprint_data"]["fingerprint_data"],
        "machine_id": validation["fingerprint_data"]["machine_id"],
        "project_slug": project_slug,
        "stamped_at": datetime.now(timezone.utc).isoformat(),
        "version": "V1",
    }
    
    license_file = store_path / "license.json"
    with open(license_file, "w") as f:
        json.dump(license_data, f, indent=2)


def verify_knowledge_store(
    knowledge_store_path: str,
    license_key: str,
    project_slug: str,
) -> bool:
    """
    Verify that a knowledge store's license stamp matches the current license.
    
    Args:
        knowledge_store_path: Path to knowledge store
        license_key: Current project license key
        project_slug: Current project slug
    
    Returns:
        True if stamp is valid
    
    Raises:
        LicenseError: If stamp is missing, invalid, or doesn't match
    """
    store_path = Path(knowledge_store_path)
    license_file = store_path / "license.json"
    
    if not license_file.exists():
        raise LicenseError(
            f"Knowledge store is not licensed.\n"
            f"Run ingest with a valid project license to stamp the knowledge store."
        )
    
    with open(license_file) as f:
        stamp = json.load(f)
    
    # Verify license key hash matches
    current_hash = hashlib.sha256(license_key.encode()).hexdigest()
    if stamp.get("license_key_hash") != current_hash:
        raise LicenseError(
            f"Knowledge store was created with a different license.\n"
            f"Cannot use this knowledge store with the current license."
        )
    
    # Verify fingerprint matches
    current_fp = generate_project_fingerprint(project_slug, str(store_path))
    if stamp.get("fingerprint") != current_fp["fingerprint"]:
        raise LicenseError(
            f"Knowledge store fingerprint mismatch.\n"
            f"This knowledge store has been moved or the machine has changed.\n"
            f"Expected: {stamp.get('fingerprint')}\n"
            f"Current:  {current_fp['fingerprint']}"
        )
    
    return True
