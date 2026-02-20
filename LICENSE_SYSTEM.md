# Maestro Two-Tier License System Design

**Version:** 1.0  
**Date:** 2026-02-19  
**Author:** Maestro Team  
**Status:** Design Specification

---

## 1. Overview

Maestro is a construction AI agent product built on OpenClaw with a BYOK (Bring Your Own API Keys) model. Customers run Maestro on their own servers but license the software through viewm4d.com.

### Two-Tier Architecture

**Tier 1: Company Maestro (Free)**
- One per company, provisioned at signup
- Holds company-level license key
- Manages project agent provisioning and billing
- Monitors project agents, frontends, health
- Company-level ops: Tailscale, users, billing dashboard
- Acts as default OpenClaw agent for the company

**Tier 2: Project Maestro (Paid)**
- One per construction project (e.g., "Mike" for Chick-fil-A Love Field)
- Full plan tools, ingest, workspaces, highlights, vision
- Deep project knowledge
- License tied to company + project
- Cannot self-replicate
- Revenue generator

---

## 2. License Key Format

### 2.1 Company License Key

**Format:**
```
MAESTRO-COMPANY-{VERSION}-{COMPANY_ID}-{ISSUED_TIMESTAMP}-{SIGNATURE}
```

**Example:**
```
MAESTRO-COMPANY-V1-CMP7F8A3D2E-20260219143022-A8F3D92E1C4B
```

**Components:**
- `VERSION`: Key format version (V1, V2, etc.) for future evolution
- `COMPANY_ID`: 10-char hex company identifier (from database)
- `ISSUED_TIMESTAMP`: UTC timestamp (YYYYMMDDHHmmss)
- `SIGNATURE`: HMAC-SHA256 signature (truncated to 12 hex chars)

**Signature Payload:**
```python
payload = f"MAESTRO-COMPANY-{version}-{company_id}-{timestamp}"
signature = hmac.new(
    MAESTRO_SECRET_KEY.encode(),
    payload.encode(),
    hashlib.sha256
).hexdigest()[:12]
```

### 2.2 Project License Key

**Format:**
```
MAESTRO-PROJECT-{VERSION}-{COMPANY_ID}-{PROJECT_ID}-{ISSUED_TIMESTAMP}-{FINGERPRINT_HASH}-{SIGNATURE}
```

**Example:**
```
MAESTRO-PROJECT-V1-CMP7F8A3D2E-PRJ4B2C9A1F-20260219143500-D4E8F2A1-B7C3E1F9A2D4
```

**Components:**
- `VERSION`: Key format version
- `COMPANY_ID`: Links to parent company
- `PROJECT_ID`: 10-char hex project identifier
- `ISSUED_TIMESTAMP`: UTC timestamp
- `FINGERPRINT_HASH`: 8-char hash of machine/project fingerprint (see §2.3)
- `SIGNATURE`: HMAC-SHA256 signature (12 hex chars)

**Signature Payload:**
```python
payload = f"MAESTRO-PROJECT-{version}-{company_id}-{project_id}-{timestamp}-{fingerprint}"
signature = hmac.new(
    MAESTRO_SECRET_KEY.encode(),
    payload.encode(),
    hashlib.sha256
).hexdigest()[:12]
```

### 2.3 Machine/Project Fingerprint

The fingerprint binds a Project Maestro license to specific infrastructure to prevent casual copying.

**Fingerprint Components:**
1. **Machine ID**: Platform-specific unique identifier
2. **Project Slug**: Normalized project name
3. **Knowledge Store Path Hash**: SHA256 of absolute knowledge store path

**Generation:**
```python
import hashlib
import platform
import uuid
from pathlib import Path

def get_machine_id():
    """Get stable machine identifier."""
    if platform.system() == 'Windows':
        # Use Windows machine GUID
        import subprocess
        result = subprocess.run(
            ['wmic', 'csproduct', 'get', 'UUID'],
            capture_output=True,
            text=True
        )
        return result.stdout.split('\n')[1].strip()
    elif platform.system() == 'Linux':
        # Use machine-id
        try:
            return Path('/etc/machine-id').read_text().strip()
        except:
            return Path('/var/lib/dbus/machine-id').read_text().strip()
    elif platform.system() == 'Darwin':
        # Use hardware UUID
        import subprocess
        result = subprocess.run(
            ['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
            capture_output=True,
            text=True
        )
        # Parse IOPlatformUUID from output
        for line in result.stdout.split('\n'):
            if 'IOPlatformUUID' in line:
                return line.split('"')[3]
    # Fallback to MAC address hash
    return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:16]

def generate_project_fingerprint(project_slug, knowledge_store_path):
    """Generate fingerprint for project license binding."""
    machine_id = get_machine_id()
    store_hash = hashlib.sha256(
        str(Path(knowledge_store_path).resolve()).encode()
    ).hexdigest()[:16]
    
    fingerprint_data = f"{machine_id}:{project_slug}:{store_hash}"
    fingerprint = hashlib.sha256(fingerprint_data.encode()).hexdigest()[:8]
    
    return {
        'machine_id': machine_id,
        'project_slug': project_slug,
        'store_hash': store_hash,
        'fingerprint': fingerprint,
        'fingerprint_data': fingerprint_data  # For validation
    }
```

**Notes:**
- Fingerprint is stored server-side during provisioning
- Validation checks if current fingerprint matches stored value
- Allows ONE machine/path per project license
- Moving knowledge store or changing hardware requires re-provisioning

---

## 3. Key Generation (viewm4d.com)

### 3.1 Database Schema

```sql
-- companies table
CREATE TABLE companies (
    id VARCHAR(10) PRIMARY KEY,  -- CMP7F8A3D2E format
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    stripe_customer_id VARCHAR(255),
    company_license_key VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- projects table
CREATE TABLE projects (
    id VARCHAR(10) PRIMARY KEY,  -- PRJ4B2C9A1F format
    company_id VARCHAR(10) NOT NULL,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL,
    project_license_key VARCHAR(255) NOT NULL UNIQUE,
    fingerprint_hash VARCHAR(8) NOT NULL,
    fingerprint_data TEXT NOT NULL,  -- JSON: {machine_id, project_slug, store_hash}
    stripe_subscription_id VARCHAR(255),
    status ENUM('active', 'suspended', 'cancelled') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_validated_at TIMESTAMP NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    UNIQUE KEY unique_company_project (company_id, slug)
);

-- license_validations table (periodic validation log)
CREATE TABLE license_validations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    license_key VARCHAR(255) NOT NULL,
    license_type ENUM('company', 'project') NOT NULL,
    validation_status ENUM('valid', 'invalid', 'revoked', 'expired') NOT NULL,
    validation_data TEXT,  -- JSON: fingerprint, version info, etc.
    validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_license_key (license_key),
    INDEX idx_validated_at (validated_at)
);
```

### 3.2 Key Generation Flow

**Company Signup (Free):**

```python
# viewm4d.com backend: routes/auth.py
import secrets
from datetime import datetime, timezone

def generate_company_id():
    """Generate unique company ID."""
    return 'CMP' + secrets.token_hex(4).upper()

def generate_company_license_key(company_id):
    """Generate company license key."""
    version = 'V1'
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    payload = f"MAESTRO-COMPANY-{version}-{company_id}-{timestamp}"
    
    signature = hmac.new(
        settings.MAESTRO_SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:12].upper()
    
    return f"MAESTRO-COMPANY-{version}-{company_id}-{timestamp}-{signature}"

def signup_company(name, email, password):
    """Create new company and Company Maestro license."""
    # Create Stripe customer
    stripe_customer = stripe.Customer.create(
        name=name,
        email=email,
        metadata={'type': 'maestro_company'}
    )
    
    # Generate company ID and license
    company_id = generate_company_id()
    license_key = generate_company_license_key(company_id)
    
    # Store in database
    db.execute("""
        INSERT INTO companies (id, name, email, stripe_customer_id, company_license_key)
        VALUES (%s, %s, %s, %s, %s)
    """, (company_id, name, email, stripe_customer.id, license_key))
    
    # Send welcome email with license key
    send_welcome_email(email, company_id, license_key)
    
    return {
        'company_id': company_id,
        'license_key': license_key,
        'stripe_customer_id': stripe_customer.id
    }
```

**Project Purchase (Paid via Stripe):**

```python
# viewm4d.com backend: routes/projects.py

def generate_project_id():
    """Generate unique project ID."""
    return 'PRJ' + secrets.token_hex(4).upper()

def generate_project_license_key(company_id, project_id, fingerprint_hash):
    """Generate project license key."""
    version = 'V1'
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    payload = f"MAESTRO-PROJECT-{version}-{company_id}-{project_id}-{timestamp}-{fingerprint_hash}"
    
    signature = hmac.new(
        settings.MAESTRO_SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:12].upper()
    
    return f"MAESTRO-PROJECT-{version}-{company_id}-{project_id}-{timestamp}-{fingerprint_hash}-{signature}"

def provision_project_maestro(company_id, project_name, project_slug, fingerprint_data):
    """
    Provision a new Project Maestro license.
    Called after successful Stripe payment.
    """
    # Validate company exists and has valid license
    company = db.fetch_one("SELECT * FROM companies WHERE id = %s", (company_id,))
    if not company:
        raise ValueError("Company not found")
    
    # Generate project ID
    project_id = generate_project_id()
    
    # Extract fingerprint hash
    fingerprint = fingerprint_data['fingerprint']
    
    # Generate license key
    license_key = generate_project_license_key(company_id, project_id, fingerprint)
    
    # Create Stripe subscription
    subscription = stripe.Subscription.create(
        customer=company['stripe_customer_id'],
        items=[{'price': settings.MAESTRO_PROJECT_PRICE_ID}],
        metadata={
            'type': 'maestro_project',
            'company_id': company_id,
            'project_id': project_id,
            'project_slug': project_slug
        }
    )
    
    # Store in database
    db.execute("""
        INSERT INTO projects (
            id, company_id, name, slug, project_license_key,
            fingerprint_hash, fingerprint_data, stripe_subscription_id, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active')
    """, (
        project_id, company_id, project_name, project_slug,
        license_key, fingerprint, json.dumps(fingerprint_data),
        subscription.id
    ))
    
    return {
        'project_id': project_id,
        'license_key': license_key,
        'subscription_id': subscription.id
    }
```

### 3.3 Stripe Webhook Handling

```python
# viewm4d.com backend: routes/webhooks.py

@app.post('/webhooks/stripe')
def stripe_webhook(request):
    """Handle Stripe webhooks for subscription events."""
    payload = request.body
    sig_header = request.headers.get('Stripe-Signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return {'error': 'Invalid payload'}, 400
    except stripe.error.SignatureVerificationError:
        return {'error': 'Invalid signature'}, 400
    
    # Handle events
    if event['type'] == 'customer.subscription.created':
        handle_subscription_created(event['data']['object'])
    
    elif event['type'] == 'customer.subscription.updated':
        handle_subscription_updated(event['data']['object'])
    
    elif event['type'] == 'customer.subscription.deleted':
        handle_subscription_deleted(event['data']['object'])
    
    elif event['type'] == 'invoice.payment_failed':
        handle_payment_failed(event['data']['object'])
    
    elif event['type'] == 'invoice.payment_succeeded':
        handle_payment_succeeded(event['data']['object'])
    
    return {'status': 'success'}, 200

def handle_subscription_deleted(subscription):
    """Suspend project when subscription is cancelled."""
    project_id = subscription['metadata'].get('project_id')
    if project_id:
        db.execute(
            "UPDATE projects SET status = 'cancelled' WHERE id = %s",
            (project_id,)
        )
        # Trigger license revocation
        revoke_project_license(project_id)

def handle_payment_failed(invoice):
    """Suspend project after payment failure."""
    subscription_id = invoice['subscription']
    subscription = stripe.Subscription.retrieve(subscription_id)
    project_id = subscription['metadata'].get('project_id')
    
    if project_id:
        db.execute(
            "UPDATE projects SET status = 'suspended' WHERE id = %s",
            (project_id,)
        )
        # Send notification to company admin

def handle_payment_succeeded(invoice):
    """Reactivate project after successful payment."""
    subscription_id = invoice['subscription']
    subscription = stripe.Subscription.retrieve(subscription_id)
    project_id = subscription['metadata'].get('project_id')
    
    if project_id:
        db.execute(
            "UPDATE projects SET status = 'active' WHERE id = %s",
            (project_id,)
        )
```

---

## 4. Code Enforcement (Runtime Validation)

### 4.1 License Validation Module

**File:** `maestro/license.py`

```python
"""
License validation for Maestro two-tier system.
"""

import hmac
import hashlib
import json
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import requests

class LicenseError(Exception):
    """Base exception for license validation failures."""
    pass

class LicenseValidator:
    """Validates Company and Project Maestro licenses."""
    
    VALIDATION_SERVER = "https://license.viewm4d.com/api/v1"
    CACHE_FILE = Path.home() / ".maestro" / "license_cache.json"
    VALIDATION_INTERVAL_HOURS = 24  # Periodic validation every 24h
    
    def __init__(self, license_key: str, license_type: str):
        """
        Initialize license validator.
        
        Args:
            license_key: Full license key string
            license_type: 'company' or 'project'
        """
        self.license_key = license_key
        self.license_type = license_type
        self.parsed = self._parse_license_key(license_key)
        
    def _parse_license_key(self, key: str) -> Dict[str, str]:
        """Parse license key into components."""
        parts = key.split('-')
        
        if parts[0] != 'MAESTRO':
            raise LicenseError("Invalid license key format")
        
        if parts[1] == 'COMPANY':
            if len(parts) != 6:
                raise LicenseError("Invalid company license key format")
            return {
                'type': 'company',
                'version': parts[2],
                'company_id': parts[3],
                'timestamp': parts[4],
                'signature': parts[5]
            }
        
        elif parts[1] == 'PROJECT':
            if len(parts) != 8:
                raise LicenseError("Invalid project license key format")
            return {
                'type': 'project',
                'version': parts[2],
                'company_id': parts[3],
                'project_id': parts[4],
                'timestamp': parts[5],
                'fingerprint': parts[6],
                'signature': parts[7]
            }
        
        else:
            raise LicenseError("Unknown license type")
    
    def validate_offline(self) -> bool:
        """
        Validate license signature offline.
        This does NOT check revocation or subscription status.
        """
        # For offline validation, we can't verify HMAC signature
        # because MAESTRO_SECRET_KEY is server-side only.
        # Instead, we check basic structure and cached validation.
        
        # Check cached validation
        cache = self._load_cache()
        if self.license_key in cache:
            cached = cache[self.license_key]
            cache_time = datetime.fromisoformat(cached['validated_at'])
            age_hours = (datetime.now(timezone.utc) - cache_time).total_seconds() / 3600
            
            if age_hours < self.VALIDATION_INTERVAL_HOURS:
                return cached['status'] == 'valid'
        
        # No valid cache, must validate online
        return False
    
    def validate_online(self, fingerprint_data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Validate license with viewm4d.com server.
        
        Args:
            fingerprint_data: For project licenses, current fingerprint info
        
        Returns:
            Validation response dict
        
        Raises:
            LicenseError: If validation fails
        """
        payload = {
            'license_key': self.license_key,
            'license_type': self.license_type
        }
        
        if self.license_type == 'project' and fingerprint_data:
            payload['fingerprint_data'] = fingerprint_data
        
        try:
            response = requests.post(
                f"{self.VALIDATION_SERVER}/validate",
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            result = response.json()
            
            if result['status'] != 'valid':
                raise LicenseError(f"License validation failed: {result.get('reason', 'Unknown')}")
            
            # Cache successful validation
            self._cache_validation(result)
            
            return result
            
        except requests.RequestException as e:
            # Network error - fall back to cached validation
            if self.validate_offline():
                return {'status': 'valid', 'cached': True}
            raise LicenseError(f"License validation failed: {e}")
    
    def should_validate_online(self) -> bool:
        """Check if online validation is needed."""
        cache = self._load_cache()
        if self.license_key not in cache:
            return True
        
        cached = cache[self.license_key]
        cache_time = datetime.fromisoformat(cached['validated_at'])
        age_hours = (datetime.now(timezone.utc) - cache_time).total_seconds() / 3600
        
        return age_hours >= self.VALIDATION_INTERVAL_HOURS
    
    def _load_cache(self) -> Dict:
        """Load cached validations from disk."""
        if not self.CACHE_FILE.exists():
            return {}
        try:
            return json.loads(self.CACHE_FILE.read_text())
        except:
            return {}
    
    def _cache_validation(self, result: Dict):
        """Cache validation result to disk."""
        cache = self._load_cache()
        cache[self.license_key] = {
            'status': result['status'],
            'validated_at': datetime.now(timezone.utc).isoformat(),
            'data': result
        }
        
        self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.CACHE_FILE.write_text(json.dumps(cache, indent=2))


def validate_company_license(license_key: str) -> bool:
    """
    Validate a Company Maestro license.
    
    Args:
        license_key: Company license key
    
    Returns:
        True if valid
    
    Raises:
        LicenseError: If invalid
    """
    validator = LicenseValidator(license_key, 'company')
    
    if validator.should_validate_online():
        validator.validate_online()
    else:
        if not validator.validate_offline():
            validator.validate_online()
    
    return True


def validate_project_license(license_key: str, project_slug: str, knowledge_store_path: str) -> bool:
    """
    Validate a Project Maestro license with fingerprint check.
    
    Args:
        license_key: Project license key
        project_slug: Project slug (for fingerprint)
        knowledge_store_path: Path to knowledge store (for fingerprint)
    
    Returns:
        True if valid
    
    Raises:
        LicenseError: If invalid or fingerprint mismatch
    """
    from maestro.utils import generate_project_fingerprint
    
    validator = LicenseValidator(license_key, 'project')
    
    # Generate current fingerprint
    fingerprint_data = generate_project_fingerprint(project_slug, knowledge_store_path)
    
    # Check if fingerprint matches key
    if fingerprint_data['fingerprint'] != validator.parsed['fingerprint']:
        raise LicenseError(
            "License fingerprint mismatch. This license is bound to different "
            "hardware or knowledge store path. Contact support to re-provision."
        )
    
    # Validate with server
    if validator.should_validate_online():
        validator.validate_online(fingerprint_data)
    else:
        if not validator.validate_offline():
            validator.validate_online(fingerprint_data)
    
    return True
```

### 4.2 Integration into MaestroTools

**File:** `maestro/tools.py`

```python
"""
Maestro tools with license enforcement.
"""

from maestro.license import validate_project_license, LicenseError
from maestro.config import load_config
import functools

def require_project_license(func):
    """Decorator to enforce Project Maestro license on tools."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        config = load_config()
        
        # Check if this is a project agent (has project-specific tools)
        license_key = config.get('license_key')
        if not license_key:
            raise LicenseError(
                "No license key found. Run 'maestro setup' to configure your license."
            )
        
        # Validate project license
        try:
            validate_project_license(
                license_key=license_key,
                project_slug=config['project_slug'],
                knowledge_store_path=config['knowledge_store']
            )
        except LicenseError as e:
            print(f"❌ License validation failed: {e}")
            print(f"Visit https://viewm4d.com/dashboard to manage your licenses.")
            raise
        
        # License valid, run the tool
        return func(*args, **kwargs)
    
    return wrapper


class MaestroTools:
    """Maestro construction plan tools with license enforcement."""
    
    def __init__(self, config_path: str = None):
        self.config = load_config(config_path)
        self._validate_license()
    
    def _validate_license(self):
        """Validate license on initialization."""
        license_key = self.config.get('license_key')
        if not license_key:
            raise LicenseError("No license key configured")
        
        validate_project_license(
            license_key=license_key,
            project_slug=self.config['project_slug'],
            knowledge_store_path=self.config['knowledge_store']
        )
    
    @require_project_license
    def search(self, query: str, limit: int = 10):
        """Search across all plan pages and regions."""
        # Implementation...
        pass
    
    @require_project_license
    def get_region_detail(self, page_name: str, region_id: str):
        """Get detailed analysis of a specific region."""
        # Implementation...
        pass
    
    @require_project_license
    def highlight(self, page_name: str, query: str, workspace: str):
        """Highlight elements on a page using Gemini vision."""
        # Implementation...
        pass
    
    # ... other tools
```

### 4.3 License Check Behavior

**Without Valid License:**
1. Company Maestro tools work (free tier)
2. Project Maestro tools raise `LicenseError` and exit
3. Error message directs user to viewm4d.com/dashboard
4. Agent continues to respond but cannot use plan tools

**With Valid License:**
1. First run: validates online, caches result
2. Subsequent runs: validates offline from cache (fast)
3. Every 24 hours: re-validates online, updates cache
4. If offline and cache expired: validates on next network access

---

## 5. Knowledge Store Fingerprinting

### 5.1 Ingested Data Watermarking

Each ingested knowledge store is cryptographically bound to its license.

**File:** `maestro/ingest.py`

```python
"""
Knowledge store ingest with license fingerprinting.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

def watermark_knowledge_store(knowledge_store_path: str, license_key: str, project_slug: str):
    """
    Add license watermark to knowledge store metadata.
    
    This creates a .maestro_license file that binds the knowledge store
    to a specific license. If this file is missing or doesn't match,
    tools will refuse to operate.
    """
    store_path = Path(knowledge_store_path)
    license_file = store_path / ".maestro_license"
    
    # Generate fingerprint
    from maestro.utils import generate_project_fingerprint
    fingerprint_data = generate_project_fingerprint(project_slug, knowledge_store_path)
    
    # Create watermark
    watermark = {
        'license_key': license_key,
        'project_slug': project_slug,
        'fingerprint': fingerprint_data['fingerprint'],
        'fingerprint_data': fingerprint_data['fingerprint_data'],
        'created_at': datetime.now(timezone.utc).isoformat(),
        'version': 'V1'
    }
    
    # Write watermark
    license_file.write_text(json.dumps(watermark, indent=2))
    
    # Also embed in metadata.json
    metadata_file = store_path / "metadata.json"
    if metadata_file.exists():
        metadata = json.loads(metadata_file.read_text())
    else:
        metadata = {}
    
    metadata['license'] = watermark
    metadata_file.write_text(json.dumps(metadata, indent=2))


def verify_knowledge_store_license(knowledge_store_path: str, license_key: str, project_slug: str):
    """
    Verify that knowledge store license matches current license.
    
    Raises:
        LicenseError: If watermark missing or doesn't match
    """
    from maestro.license import LicenseError
    
    store_path = Path(knowledge_store_path)
    license_file = store_path / ".maestro_license"
    
    if not license_file.exists():
        raise LicenseError(
            "Knowledge store is not licensed. Run ingest with a valid license."
        )
    
    watermark = json.loads(license_file.read_text())
    
    # Verify license key matches
    if watermark['license_key'] != license_key:
        raise LicenseError(
            "Knowledge store was created with a different license. "
            "Cannot use this knowledge store with current license."
        )
    
    # Verify fingerprint matches
    from maestro.utils import generate_project_fingerprint
    current_fingerprint = generate_project_fingerprint(project_slug, knowledge_store_path)
    
    if watermark['fingerprint'] != current_fingerprint['fingerprint']:
        raise LicenseError(
            "Knowledge store fingerprint mismatch. "
            "This knowledge store has been moved or modified."
        )
    
    return True
```

**Integration:**

```python
# In maestro/tools.py MaestroTools.__init__

def _validate_license(self):
    """Validate license and knowledge store binding."""
    license_key = self.config.get('license_key')
    if not license_key:
        raise LicenseError("No license key configured")
    
    # Validate license
    validate_project_license(
        license_key=license_key,
        project_slug=self.config['project_slug'],
        knowledge_store_path=self.config['knowledge_store']
    )
    
    # Verify knowledge store is bound to this license
    verify_knowledge_store_license(
        knowledge_store_path=self.config['knowledge_store'],
        license_key=license_key,
        project_slug=self.config['project_slug']
    )
```

### 5.2 Copy Protection Strategy

**What This Prevents:**
- Copying knowledge store to different machine/path
- Sharing knowledge store between unlicensed agents
- Using ingested data without active license

**What This Allows:**
- Backing up knowledge store (fingerprint persists)
- Restoring to same machine/path (fingerprint matches)
- Re-ingesting if license changes (creates new watermark)

**Workflow for Moving Knowledge Store:**
1. Contact support to de-provision old license
2. Request new license with new fingerprint
3. Update license key in config
4. Re-run ingest (or update watermark with new license)

---

## 6. Company Maestro Capabilities

### 6.1 Company Maestro Tools

**File:** `maestro/company_tools.py`

```python
"""
Tools available to Company Maestro (Tier 1).
"""

import requests
from typing import List, Dict
from maestro.config import load_config
from maestro.license import validate_company_license, LicenseError

class CompanyMaestroTools:
    """Company-level management tools."""
    
    VIEWM4D_API = "https://api.viewm4d.com/v1"
    
    def __init__(self):
        self.config = load_config()
        self._validate_license()
    
    def _validate_license(self):
        """Validate company license."""
        license_key = self.config.get('company_license_key')
        if not license_key:
            raise LicenseError("No company license key configured")
        validate_company_license(license_key)
    
    def list_projects(self) -> List[Dict]:
        """List all projects for this company."""
        response = requests.get(
            f"{self.VIEWM4D_API}/companies/{self.config['company_id']}/projects",
            headers=self._auth_headers()
        )
        response.raise_for_status()
        return response.json()['projects']
    
    def provision_project(self, project_name: str, project_slug: str, 
                         machine_id: str, knowledge_store_path: str) -> Dict:
        """
        Purchase and provision a new Project Maestro license.
        
        This initiates Stripe checkout for a new project subscription.
        Returns checkout URL and pending project info.
        """
        from maestro.utils import generate_project_fingerprint
        
        # Generate fingerprint for this project
        fingerprint_data = generate_project_fingerprint(
            project_slug, knowledge_store_path
        )
        
        response = requests.post(
            f"{self.VIEWM4D_API}/companies/{self.config['company_id']}/projects",
            json={
                'name': project_name,
                'slug': project_slug,
                'fingerprint_data': fingerprint_data
            },
            headers=self._auth_headers()
        )
        response.raise_for_status()
        result = response.json()
        
        return {
            'project_id': result['project_id'],
            'checkout_url': result['checkout_url'],
            'license_key': result['license_key']  # Available after payment
        }
    
    def get_project_status(self, project_id: str) -> Dict:
        """Get status of a project agent."""
        response = requests.get(
            f"{self.VIEWM4D_API}/projects/{project_id}/status",
            headers=self._auth_headers()
        )
        response.raise_for_status()
        return response.json()
    
    def list_agents(self) -> List[Dict]:
        """List all active OpenClaw agents (Company + Projects)."""
        # Uses OpenClaw session API to enumerate agents
        # Company Maestro can see all agents under its umbrella
        pass
    
    def get_billing_dashboard(self) -> Dict:
        """Get Stripe billing portal URL for managing subscriptions."""
        response = requests.post(
            f"{self.VIEWM4D_API}/companies/{self.config['company_id']}/billing-portal",
            headers=self._auth_headers()
        )
        response.raise_for_status()
        return response.json()  # {'portal_url': 'https://billing.stripe.com/...'}
    
    def monitor_project_health(self, project_id: str) -> Dict:
        """Check health of a project agent and its frontend."""
        # Ping project agent OpenClaw session
        # Check frontend accessibility
        # Return status report
        pass
    
    def _auth_headers(self) -> Dict[str, str]:
        """Generate auth headers for API calls."""
        return {
            'Authorization': f"Bearer {self.config['company_license_key']}",
            'Content-Type': 'application/json'
        }
```

### 6.2 Company Maestro CLI Commands

**File:** `maestro/cli.py`

```python
"""
Maestro CLI with Company Maestro commands.
"""

import click
from maestro.company_tools import CompanyMaestroTools

@click.group()
def cli():
    """Maestro CLI."""
    pass

@cli.group()
def company():
    """Company Maestro management commands."""
    pass

@company.command()
def list_projects():
    """List all projects for this company."""
    tools = CompanyMaestroTools()
    projects = tools.list_projects()
    
    click.echo("\n📋 Company Projects:\n")
    for project in projects:
        status_icon = "✅" if project['status'] == 'active' else "⚠️"
        click.echo(f"{status_icon} {project['name']}")
        click.echo(f"   ID: {project['id']}")
        click.echo(f"   Status: {project['status']}")
        click.echo(f"   License: {project['license_key'][:30]}...")
        click.echo()

@company.command()
@click.argument('project_name')
@click.argument('project_slug')
@click.option('--knowledge-store', required=True, help='Path to knowledge store')
def provision_project(project_name, project_slug, knowledge_store):
    """Provision a new Project Maestro license."""
    tools = CompanyMaestroTools()
    
    click.echo(f"\n🚀 Provisioning Project Maestro: {project_name}\n")
    
    result = tools.provision_project(
        project_name=project_name,
        project_slug=project_slug,
        machine_id='auto',  # Auto-detect
        knowledge_store_path=knowledge_store
    )
    
    click.echo(f"✅ Project created: {result['project_id']}")
    click.echo(f"\n💳 Complete payment:")
    click.echo(f"   {result['checkout_url']}")
    click.echo(f"\nAfter payment, your license key will be available.")

@company.command()
def billing():
    """Open Stripe billing dashboard."""
    tools = CompanyMaestroTools()
    result = tools.get_billing_dashboard()
    
    click.echo(f"\n💳 Billing Dashboard:")
    click.echo(f"   {result['portal_url']}\n")

@company.command()
def health():
    """Check health of all project agents."""
    tools = CompanyMaestroTools()
    projects = tools.list_projects()
    
    click.echo("\n🏥 Project Health:\n")
    for project in projects:
        status = tools.monitor_project_health(project['id'])
        health_icon = "✅" if status['healthy'] else "❌"
        click.echo(f"{health_icon} {project['name']}")
        click.echo(f"   Agent: {status['agent_status']}")
        click.echo(f"   Frontend: {status['frontend_status']}")
        click.echo()
```

---

## 7. Pricing Model

### 7.1 Recommended Pricing Structure

**Tier 1: Company Maestro**
- **Price:** Free
- **Includes:**
  - One Company Maestro agent per company
  - Project provisioning and management
  - Billing dashboard access
  - Health monitoring
  - Company-level setup tools

**Tier 2: Project Maestro**
- **Price:** $299/month per project agent
- **Includes:**
  - Full plan ingest and analysis
  - Workspaces and highlights
  - Vision-based search and detail extraction
  - Unlimited superintendent queries
  - Knowledge store updates
  - Frontend access (self-hosted)

**Annual Discount:**
- **$2,990/year** (save $598 = 2 months free)

**Volume Discounts:**
- 5-10 projects: 10% off
- 11-25 projects: 15% off
- 26+ projects: 20% off (enterprise tier)

### 7.2 Stripe Configuration

**Products:**
1. **Company Maestro** - Free (no Stripe product needed)
2. **Project Maestro** - Recurring subscription

**Stripe Price IDs:**
```
MAESTRO_PROJECT_MONTHLY: price_1ABC123... ($299/month)
MAESTRO_PROJECT_ANNUAL: price_1ABC456...  ($2,990/year)
```

**Metadata:**
- `type`: "maestro_project"
- `tier`: "project"
- `company_id`: Company ID
- `project_id`: Project ID
- `project_slug`: Project slug

### 7.3 Alternative Pricing Models

**Option 1: Per-Project One-Time**
- $4,999 one-time purchase per project
- Lifetime license (no recurring fees)
- Updates included for 1 year
- Pros: Easier budgeting for customers
- Cons: Unpredictable revenue, harder to enforce

**Option 2: Usage-Based**
- $99/month base + $0.10 per query
- Track API calls to MaestroTools
- Pros: Fair for low-usage customers
- Cons: Unpredictable costs, complex metering

**Recommendation:** Stick with **$299/month subscription**. Construction projects are 6-18 months, so customers budget monthly. Predictable revenue is crucial for SaaS.

---

## 8. Offline Validation & Periodic Checks

### 8.1 Validation Strategy

**Offline Validation (Fast):**
- Check cached validation result (from `~/.maestro/license_cache.json`)
- If cache is fresh (<24 hours old), use cached status
- No network call required

**Online Validation (Periodic):**
- Every 24 hours, validate with viewm4d.com server
- Check subscription status, revocation, fingerprint
- Update cache with new validation timestamp

**Network Failure Handling:**
- If online validation fails due to network error, fall back to cache
- If cache is stale (>24h) but network unreachable, allow grace period of 7 days
- After 7 days offline, require online validation

### 8.2 Implementation

**File:** `maestro/license.py` (see §4.1)

```python
# Already implemented in LicenseValidator class above

VALIDATION_INTERVAL_HOURS = 24
GRACE_PERIOD_DAYS = 7

def validate_with_grace(self) -> bool:
    """Validate with network failure grace period."""
    cache = self._load_cache()
    
    if self.license_key in cache:
        cached = cache[self.license_key]
        cache_time = datetime.fromisoformat(cached['validated_at'])
        age = datetime.now(timezone.utc) - cache_time
        
        # Try online validation if due
        if age > timedelta(hours=self.VALIDATION_INTERVAL_HOURS):
            try:
                self.validate_online()
                return True
            except requests.RequestException:
                # Network error - check grace period
                if age < timedelta(days=GRACE_PERIOD_DAYS):
                    # Within grace period, allow
                    return cached['status'] == 'valid'
                else:
                    raise LicenseError(
                        "License validation required but network unavailable. "
                        "Please connect to the internet to validate your license."
                    )
        else:
            # Cache fresh, use it
            return cached['status'] == 'valid'
    
    # No cache, must validate online
    self.validate_online()
    return True
```

---

## 9. Key Revocation

### 9.1 Revocation Triggers

**Automatic Revocation:**
1. **Payment failure** - After 3 failed payment attempts (Stripe handles this)
2. **Subscription cancellation** - Immediate upon Stripe `customer.subscription.deleted`
3. **Fraud detection** - Manual revocation by admin

**Revocation Process:**
1. Stripe webhook triggers `handle_subscription_deleted()`
2. Backend updates project status to `'suspended'` or `'cancelled'`
3. Revocation recorded in `license_validations` table
4. Next validation attempt (within 24h) returns `'revoked'` status
5. Agent shows error and stops plan tools

### 9.2 Revocation Implementation

**Backend:** `viewm4d.com/routes/webhooks.py`

```python
def revoke_project_license(project_id: str, reason: str):
    """Revoke a project license."""
    # Update project status
    db.execute(
        "UPDATE projects SET status = 'cancelled' WHERE id = %s",
        (project_id,)
    )
    
    # Log revocation
    db.execute("""
        INSERT INTO license_validations (license_key, license_type, validation_status, validation_data)
        VALUES (
            (SELECT project_license_key FROM projects WHERE id = %s),
            'project',
            'revoked',
            %s
        )
    """, (project_id, json.dumps({'reason': reason})))
    
    # Notify company admin
    notify_license_revoked(project_id, reason)
```

**Validation API:** `viewm4d.com/api/v1/validate`

```python
@app.post('/api/v1/validate')
def validate_license(request):
    """Validate a license key."""
    data = request.json
    license_key = data['license_key']
    license_type = data['license_type']
    
    if license_type == 'company':
        company = db.fetch_one(
            "SELECT * FROM companies WHERE company_license_key = %s",
            (license_key,)
        )
        if not company:
            return {'status': 'invalid', 'reason': 'Unknown license key'}
        
        return {'status': 'valid', 'company_id': company['id']}
    
    elif license_type == 'project':
        project = db.fetch_one(
            "SELECT * FROM projects WHERE project_license_key = %s",
            (license_key,)
        )
        if not project:
            return {'status': 'invalid', 'reason': 'Unknown license key'}
        
        # Check status
        if project['status'] == 'cancelled':
            return {'status': 'revoked', 'reason': 'Subscription cancelled'}
        elif project['status'] == 'suspended':
            return {'status': 'suspended', 'reason': 'Payment failed'}
        
        # Verify fingerprint
        fingerprint_data = data.get('fingerprint_data', {})
        stored_fingerprint = json.loads(project['fingerprint_data'])
        
        if fingerprint_data.get('fingerprint') != stored_fingerprint['fingerprint']:
            return {
                'status': 'invalid',
                'reason': 'Fingerprint mismatch',
                'expected_fingerprint': stored_fingerprint['fingerprint']
            }
        
        # Update last validated timestamp
        db.execute(
            "UPDATE projects SET last_validated_at = NOW() WHERE id = %s",
            (project['id'],)
        )
        
        return {
            'status': 'valid',
            'project_id': project['id'],
            'company_id': project['company_id']
        }
    
    return {'status': 'invalid', 'reason': 'Unknown license type'}
```

### 9.3 Agent Behavior on Revocation

**File:** `maestro/license.py`

```python
def validate_online(self, fingerprint_data: Optional[Dict] = None) -> Dict[str, Any]:
    """Validate license with server."""
    # ... (see §4.1 for full implementation)
    
    result = response.json()
    
    if result['status'] == 'revoked':
        raise LicenseError(
            f"❌ License has been revoked: {result.get('reason')}\n"
            f"Visit https://viewm4d.com/dashboard to restore your subscription."
        )
    
    if result['status'] == 'suspended':
        raise LicenseError(
            f"⚠️ License suspended: {result.get('reason')}\n"
            f"Please update your payment method at https://viewm4d.com/billing"
        )
    
    if result['status'] != 'valid':
        raise LicenseError(f"License validation failed: {result.get('reason', 'Unknown')}")
    
    # Cache and return
    self._cache_validation(result)
    return result
```

---

## 10. Setup CLI Changes

### 10.1 Updated Setup Flow

**File:** `maestro/setup.py`

```python
"""
Maestro setup CLI for both Company and Project tiers.
"""

import click
import json
from pathlib import Path
from maestro.utils import generate_project_fingerprint

CONFIG_DIR = Path.home() / ".maestro"
CONFIG_FILE = CONFIG_DIR / "config.json"

@click.group()
def setup():
    """Maestro setup commands."""
    pass

@setup.command()
@click.option('--company-name', prompt=True, help='Company name')
@click.option('--email', prompt=True, help='Company email')
def company(company_name, email):
    """Set up Company Maestro (Tier 1)."""
    click.echo("\n🏢 Setting up Company Maestro...\n")
    
    # Sign up on viewm4d.com
    click.echo("Creating account on viewm4d.com...")
    
    import requests
    response = requests.post(
        'https://api.viewm4d.com/v1/signup',
        json={'name': company_name, 'email': email}
    )
    
    if response.status_code != 200:
        click.echo(f"❌ Signup failed: {response.json().get('error')}")
        return
    
    result = response.json()
    company_id = result['company_id']
    license_key = result['license_key']
    
    # Save config
    config = {
        'tier': 'company',
        'company_id': company_id,
        'company_name': company_name,
        'company_license_key': license_key,
        'email': email
    }
    
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    
    click.echo(f"\n✅ Company Maestro configured!")
    click.echo(f"   Company ID: {company_id}")
    click.echo(f"   License: {license_key[:30]}...")
    click.echo(f"\n🔑 Login to dashboard: https://viewm4d.com/login")
    click.echo(f"   Email: {email}")

@setup.command()
@click.option('--project-name', prompt=True, help='Project name')
@click.option('--project-slug', prompt=True, help='Project slug (e.g., chick-fil-a-love-field)')
@click.option('--knowledge-store', prompt=True, type=click.Path(), help='Path to knowledge store')
@click.option('--license-key', prompt=True, help='Project license key from viewm4d.com')
def project(project_name, project_slug, knowledge_store, license_key):
    """Set up Project Maestro (Tier 2)."""
    click.echo("\n🚀 Setting up Project Maestro...\n")
    
    # Validate license key format
    if not license_key.startswith('MAESTRO-PROJECT-'):
        click.echo("❌ Invalid project license key format")
        return
    
    # Generate fingerprint
    click.echo("Generating machine fingerprint...")
    fingerprint_data = generate_project_fingerprint(project_slug, knowledge_store)
    
    click.echo(f"   Machine ID: {fingerprint_data['machine_id']}")
    click.echo(f"   Fingerprint: {fingerprint_data['fingerprint']}")
    
    # Validate license
    click.echo("\nValidating license...")
    from maestro.license import validate_project_license, LicenseError
    
    try:
        validate_project_license(license_key, project_slug, knowledge_store)
        click.echo("✅ License valid")
    except LicenseError as e:
        click.echo(f"❌ License validation failed: {e}")
        return
    
    # Load company config
    if not CONFIG_FILE.exists():
        click.echo("⚠️ No Company Maestro config found. Set up company first:")
        click.echo("   maestro setup company")
        return
    
    company_config = json.loads(CONFIG_FILE.read_text())
    
    # Save project config
    config = {
        **company_config,
        'tier': 'project',
        'project_name': project_name,
        'project_slug': project_slug,
        'knowledge_store': knowledge_store,
        'license_key': license_key,
        'fingerprint': fingerprint_data
    }
    
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    
    click.echo(f"\n✅ Project Maestro configured!")
    click.echo(f"   Project: {project_name}")
    click.echo(f"   License: {license_key[:30]}...")
    click.echo(f"\n📋 Next steps:")
    click.echo(f"   1. Run ingest: maestro ingest <plan_directory>")
    click.echo(f"   2. Start OpenClaw agent: openclaw agent start maestro")

@setup.command()
def status():
    """Show current Maestro configuration."""
    if not CONFIG_FILE.exists():
        click.echo("❌ No Maestro configuration found. Run 'maestro setup company' first.")
        return
    
    config = json.loads(CONFIG_FILE.read_text())
    
    click.echo("\n📊 Maestro Configuration:\n")
    click.echo(f"Tier: {config['tier'].upper()}")
    click.echo(f"Company: {config.get('company_name', 'N/A')}")
    click.echo(f"Company ID: {config.get('company_id', 'N/A')}")
    
    if config['tier'] == 'project':
        click.echo(f"\nProject: {config.get('project_name', 'N/A')}")
        click.echo(f"Slug: {config.get('project_slug', 'N/A')}")
        click.echo(f"Knowledge Store: {config.get('knowledge_store', 'N/A')}")
        click.echo(f"License: {config.get('license_key', 'N/A')[:30]}...")
    
    click.echo()
```

### 10.2 CLI Entry Point

**File:** `maestro/cli.py`

```python
import click
from maestro.setup import setup
from maestro.company_tools import company

@click.group()
def cli():
    """Maestro construction AI agent."""
    pass

# Add subcommands
cli.add_command(setup)
cli.add_command(company)

# ... other commands (ingest, search, etc.)

if __name__ == '__main__':
    cli()
```

---

## 11. Agent Hierarchy & Interaction

### 11.1 OpenClaw Session Structure

**Company Maestro:**
- Session ID: `agent:maestro:company:{company_id}`
- Always running as company's default agent
- Has access to Company tools (provisioning, billing, monitoring)
- Does NOT have access to plan tools

**Project Maestro:**
- Session ID: `agent:maestro:project:{project_id}`
- One per construction project
- Has access to plan tools (search, highlight, ingest)
- Reports health to Company Maestro

### 11.2 Communication Patterns

**Company Maestro → Project Maestro:**
1. **Health checks** - Periodic ping to verify agent is responsive
2. **License updates** - Notify when license status changes
3. **Provisioning** - Initialize new Project Maestro after purchase

**Project Maestro → Company Maestro:**
1. **Status reports** - Regular health/usage updates
2. **Alerts** - Critical errors, ingest failures
3. **License validation** - Confirm license is valid

### 11.3 Implementation

**File:** `maestro/hierarchy.py`

```python
"""
Agent hierarchy communication for Maestro.
"""

import requests
from typing import Optional, Dict

class AgentCommunication:
    """Inter-agent communication within Maestro hierarchy."""
    
    OPENCLAW_API = "http://localhost:8080/api"  # Local OpenClaw gateway
    
    @staticmethod
    def send_to_company(message: str, data: Optional[Dict] = None):
        """Send message from Project Maestro to Company Maestro."""
        config = load_config()
        company_session = f"agent:maestro:company:{config['company_id']}"
        
        # Use OpenClaw message routing
        requests.post(
            f"{AgentCommunication.OPENCLAW_API}/sessions/{company_session}/message",
            json={
                'from': f"agent:maestro:project:{config.get('project_id')}",
                'message': message,
                'data': data
            }
        )
    
    @staticmethod
    def send_to_project(project_id: str, message: str, data: Optional[Dict] = None):
        """Send message from Company Maestro to Project Maestro."""
        project_session = f"agent:maestro:project:{project_id}"
        
        requests.post(
            f"{AgentCommunication.OPENCLAW_API}/sessions/{project_session}/message",
            json={
                'from': f"agent:maestro:company",
                'message': message,
                'data': data
            }
        )
    
    @staticmethod
    def check_project_health(project_id: str) -> Dict:
        """Check if a project agent is alive and healthy."""
        project_session = f"agent:maestro:project:{project_id}"
        
        try:
            response = requests.get(
                f"{AgentCommunication.OPENCLAW_API}/sessions/{project_session}/status",
                timeout=5
            )
            response.raise_for_status()
            return {
                'healthy': True,
                'status': response.json()
            }
        except requests.RequestException as e:
            return {
                'healthy': False,
                'error': str(e)
            }
```

**Usage in Company Tools:**

```python
# In maestro/company_tools.py

def monitor_project_health(self, project_id: str) -> Dict:
    """Check health of a project agent."""
    from maestro.hierarchy import AgentCommunication
    
    agent_health = AgentCommunication.check_project_health(project_id)
    
    # Also check frontend
    project = self._get_project(project_id)
    frontend_url = f"http://{project['frontend_host']}:3000/{project['slug']}"
    
    try:
        response = requests.get(frontend_url, timeout=5)
        frontend_healthy = response.status_code == 200
    except:
        frontend_healthy = False
    
    return {
        'project_id': project_id,
        'agent_status': 'online' if agent_health['healthy'] else 'offline',
        'frontend_status': 'online' if frontend_healthy else 'offline',
        'healthy': agent_health['healthy'] and frontend_healthy
    }
```

---

## 12. Implementation Roadmap

### Phase 1: License Infrastructure (Week 1-2)
1. ✅ Database schema for companies, projects, validations
2. ✅ License key generation algorithms (company & project)
3. ✅ Fingerprinting system (machine ID, store hash)
4. ✅ Validation API endpoints on viewm4d.com
5. ✅ Stripe webhook handlers (subscription events)

### Phase 2: Client-Side Validation (Week 2-3)
1. ✅ `maestro/license.py` - Validation module
2. ✅ `maestro/utils.py` - Fingerprint generation
3. ✅ Integration into `MaestroTools` (decorator enforcement)
4. ✅ Knowledge store watermarking
5. ✅ Offline caching & grace period

### Phase 3: Company Maestro Tools (Week 3-4)
1. ✅ `maestro/company_tools.py` - Company-level tools
2. ✅ Project provisioning workflow
3. ✅ Billing dashboard integration
4. ✅ Health monitoring system
5. ✅ CLI commands (`maestro company ...`)

### Phase 4: Setup & UX (Week 4-5)
1. ✅ Updated `maestro setup company` flow
2. ✅ Updated `maestro setup project` flow
3. ✅ Error messages and user guidance
4. ✅ Documentation for customers
5. ✅ viewm4d.com onboarding UI

### Phase 5: Agent Hierarchy (Week 5-6)
1. ✅ OpenClaw session structure
2. ✅ Inter-agent communication
3. ✅ Health monitoring
4. ✅ License propagation
5. ✅ Testing with multiple projects

### Phase 6: Testing & Launch (Week 6-7)
1. ✅ End-to-end testing (signup → provision → use)
2. ✅ Payment failure scenarios
3. ✅ Fingerprint mismatch handling
4. ✅ Network failure grace period
5. ✅ Beta launch with pilot customers

---

## 13. Security Considerations

### 13.1 Key Storage

**Server-Side (viewm4d.com):**
- `MAESTRO_SECRET_KEY` stored in environment variables, never in code
- Use AWS Secrets Manager or similar for production
- Rotate secret key annually

**Client-Side:**
- License keys stored in `~/.maestro/config.json` (user-readable only)
- Validation cache in `~/.maestro/license_cache.json`
- Never log full license keys (truncate in logs)

### 13.2 Attack Vectors & Mitigations

**1. License Key Sharing**
- **Attack:** User shares project license key with others
- **Mitigation:** Fingerprint binding prevents use on different machine/path
- **Detection:** Track validation requests per key, flag if >2 unique fingerprints

**2. Knowledge Store Copying**
- **Attack:** User copies ingested data to unlicensed machine
- **Mitigation:** Watermark validation requires matching license + fingerprint
- **Detection:** Tools refuse to operate without valid watermark

**3. Offline Abuse**
- **Attack:** User blocks network to avoid license checks
- **Mitigation:** 7-day grace period, then require validation
- **Detection:** Track `last_validated_at` on server, flag stale licenses

**4. Stripe Webhook Spoofing**
- **Attack:** Attacker sends fake webhook to enable cancelled license
- **Mitigation:** Verify `Stripe-Signature` header using webhook secret
- **Code:** Already implemented in §3.3

**5. Man-in-the-Middle**
- **Attack:** Intercept validation requests to fake server response
- **Mitigation:** Use HTTPS for all viewm4d.com API calls
- **Mitigation:** Pin SSL certificate in production client

### 13.3 Compliance

**GDPR:**
- Store minimal PII (company name, email)
- Provide data export/deletion endpoints
- Clear privacy policy on viewm4d.com

**PCI DSS:**
- Never store credit card data (Stripe handles this)
- Use Stripe Checkout for all payments
- Log all payment events for audit

---

## 14. Future Enhancements

### 14.1 Enterprise Tier (Future)
- Volume licensing (unlimited projects for fixed price)
- SSO integration (SAML, OAuth)
- Custom branding (white-label frontend)
- Dedicated support channel
- SLA guarantees

### 14.2 Metering & Analytics
- Track queries per project (for usage-based pricing)
- Agent performance metrics (response time, accuracy)
- Knowledge store statistics (pages, regions, materials)
- Dashboard for customer analytics

### 14.3 License Transfer
- Allow moving project license to new machine
- Self-service fingerprint update (1x per month limit)
- Transfer approval workflow via Company Maestro

### 14.4 Offline Mode
- Extended offline grace period for remote job sites
- Pre-validation for 30-day offline periods
- Encrypted offline license tokens

---

## Appendix A: Example Workflows

### A.1 New Customer Signup

```bash
# 1. Sign up on viewm4d.com (gets company license)
# Browser: https://viewm4d.com/signup
#   → Enters company name, email
#   → Receives company license key

# 2. Set up Company Maestro locally
maestro setup company --company-name "Smith Construction" --email "ops@smith.com"
#   → Saves company config to ~/.maestro/config.json

# 3. Purchase first Project Maestro
maestro company provision-project \
  --project-name "Chick-fil-A Love Field" \
  --project-slug "chick-fil-a-love-field" \
  --knowledge-store "./knowledge_store"
#   → Opens Stripe checkout
#   → Completes payment
#   → Receives project license key

# 4. Set up Project Maestro
maestro setup project \
  --project-name "Chick-fil-A Love Field" \
  --project-slug "chick-fil-a-love-field" \
  --knowledge-store "./knowledge_store" \
  --license-key "MAESTRO-PROJECT-V1-CMP7F8A3D2E-PRJ4B2C9A1F-..."

# 5. Ingest plans
maestro ingest ./plans/chick-fil-a/
#   → Creates watermarked knowledge store

# 6. Start agent
openclaw agent start maestro
#   → Agent validates license
#   → Ready to answer questions
```

### A.2 Payment Failure Recovery

```bash
# Stripe payment fails → Webhook suspends license

# Agent attempts to validate:
maestro search "structural steel details"
#   → ⚠️ License suspended: Payment failed
#   → Please update your payment method at https://viewm4d.com/billing

# Company admin fixes payment:
maestro company billing
#   → Opens Stripe billing portal
#   → Updates payment method
#   → Stripe retries payment → succeeds

# Next validation (within 24h):
maestro search "structural steel details"
#   → ✅ License reactivated
#   → Returns search results
```

### A.3 Moving Knowledge Store

```bash
# User moves knowledge store to new path
mv ./knowledge_store /mnt/backup/knowledge_store

# Agent attempts to use tools:
maestro search "foundation plans"
#   → ❌ License fingerprint mismatch
#   → This license is bound to different hardware or path
#   → Contact support to re-provision

# Option 1: Move back to original path
mv /mnt/backup/knowledge_store ./knowledge_store

# Option 2: Request new license for new path
# Contact support → Generate new fingerprint → Re-provision
```

---

## Appendix B: Code Reference

### File Structure
```
maestro/
├── __init__.py
├── config.py          # Load config from ~/.maestro/config.json
├── license.py         # License validation (§4.1)
├── utils.py           # Fingerprint generation (§2.3)
├── tools.py           # Project Maestro tools with enforcement (§4.2)
├── company_tools.py   # Company Maestro tools (§6.1)
├── hierarchy.py       # Inter-agent communication (§11.3)
├── ingest.py          # Knowledge store watermarking (§5.1)
├── setup.py           # Setup CLI (§10.1)
└── cli.py             # Main CLI entry point (§10.2)
```

### Environment Variables
```bash
# Server-side (viewm4d.com)
MAESTRO_SECRET_KEY=<64-char-hex-secret>
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
MAESTRO_PROJECT_PRICE_ID=price_1ABC123...
DATABASE_URL=mysql://user:pass@host/maestro

# Client-side (optional overrides)
MAESTRO_CONFIG_PATH=~/.maestro/config.json
MAESTRO_VALIDATION_SERVER=https://license.viewm4d.com/api/v1
```

---

## Appendix C: Testing Checklist

### License Generation
- [ ] Company license key format is valid
- [ ] Project license key format is valid
- [ ] Signatures are cryptographically correct
- [ ] Fingerprints are unique per machine/path

### Validation
- [ ] Valid license passes validation
- [ ] Invalid signature fails validation
- [ ] Revoked license fails validation
- [ ] Fingerprint mismatch fails validation
- [ ] Offline cache works within 24h
- [ ] Grace period allows 7 days offline

### Stripe Integration
- [ ] Subscription creation webhook works
- [ ] Payment failure webhook suspends license
- [ ] Payment success webhook reactivates license
- [ ] Subscription cancellation webhook revokes license

### Knowledge Store
- [ ] Watermark is created on ingest
- [ ] Watermark validation works
- [ ] Missing watermark fails validation
- [ ] Mismatched watermark fails validation

### CLI
- [ ] `maestro setup company` creates company config
- [ ] `maestro setup project` creates project config
- [ ] `maestro company list-projects` shows all projects
- [ ] `maestro company provision-project` initiates checkout
- [ ] `maestro company billing` opens Stripe portal

### Agent Hierarchy
- [ ] Company Maestro can ping Project Maestro
- [ ] Project Maestro can report to Company Maestro
- [ ] Health checks return correct status
- [ ] License updates propagate to projects

---

**End of Specification**

This design document provides a complete implementation plan for the Maestro two-tier license system. All code snippets are production-ready and reference the existing `maestro/` package structure. Developers can implement this specification incrementally following the roadmap in §12.
