# License Enforcement Implementation

**Status:** ✅ Complete  
**Commit:** c5dd62b  
**Tests:** 22/22 passing

## What Was Built

A complete local cryptographic license enforcement layer for Maestro's two-tier system:
- **Company licenses** (free tier) - unlimited company-level agent
- **Project licenses** (paid tier) - per-project, machine-fingerprinted

No payment backend required — just local HMAC-SHA256 validation.

---

## Files Created/Modified

### New Files

1. **`maestro/license.py`** (12 KB)
   - Core license module with all key generation and validation functions
   - Machine fingerprinting for Windows, macOS, Linux
   - Knowledge store stamping and verification
   - Hardcoded test secret: `MAESTRO_TEST_SECRET_2026`

2. **`tests/test_license.py`** (14 KB)
   - Comprehensive test suite (22 tests, all passing)
   - Tests for company keys, project keys, fingerprinting, stamping, decorator
   - Validates tamper detection, fingerprint mismatches, moved knowledge stores

### Modified Files

3. **`maestro/tools.py`**
   - Added `@requires_license` decorator
   - License validation in `__init__` via `_validate_license()`
   - Reads `MAESTRO_LICENSE_KEY` from environment
   - All tool methods gated behind license check
   - `skip_license_check=True` parameter for testing

4. **`maestro/ingest.py`**
   - Knowledge store stamping after ingest completes
   - Creates `license.json` with fingerprint, hash, timestamp
   - Reads `MAESTRO_LICENSE_KEY` from environment

5. **`maestro/cli.py`**
   - New `maestro license` subcommand group
   - `maestro license generate-company <company_id>` — test company key
   - `maestro license generate-project <company_id> <project_id> <slug>` — test project key
   - `maestro license validate` — check current license status
   - `maestro license info` — show license details

---

## Key Functions

### License Module (`maestro/license.py`)

**Machine Fingerprinting:**
```python
get_machine_id() -> str  # Stable 16-char hardware ID
generate_project_fingerprint(slug, path) -> dict  # Combines machine + slug + path
```

**Company License:**
```python
generate_company_key(company_id) -> str
validate_company_key(key) -> dict  # Verifies HMAC signature
```

**Project License:**
```python
generate_project_key(company_id, project_id, slug, store_path) -> str
validate_project_key(key, slug, store_path) -> dict  # Verifies signature + fingerprint
```

**Knowledge Store Stamping:**
```python
stamp_knowledge_store(path, key, slug) -> None  # Creates license.json
verify_knowledge_store(path, key, slug) -> bool  # Validates stamp matches
```

---

## Usage Examples

### 1. Generate Test Licenses

**Company license:**
```bash
maestro license generate-company CMP7F8A3D2E
```

Output:
```
✅ Company License Generated:
   MAESTRO-COMPANY-V1-CMP7F8A3D2E-20260219213045-A8F3D92E1C4B
```

**Project license:**
```bash
maestro license generate-project CMP7F8A3D2E PRJ4B2C9A1F my-project --store knowledge_store
```

Output:
```
✅ Project License Generated:
   MAESTRO-PROJECT-V1-CMP7F8A3D2E-PRJ4B2C9A1F-20260219213120-D4E8F2A1-B7C3E1F9A2D4

Project: my-project
Store:   knowledge_store
Machine: afeae6a03765a572
Fingerprint: D4E8F2A1
```

### 2. Use License with Tools

**Set environment variable:**
```bash
export MAESTRO_LICENSE_KEY="MAESTRO-PROJECT-V1-CMP7F8A3D2E-PRJ4B2C9A1F-..."
```

**Run ingest (stamps knowledge store):**
```bash
maestro ingest /path/to/pdfs --project-name "My Project"
```

**Use tools:**
```bash
maestro tools search "waterproofing"
```

### 3. Validate License

```bash
maestro license validate
```

Output:
```
✅ Valid Project License
   Company ID: CMP7F8A3D2E
   Project ID: PRJ4B2C9A1F
   Version: V1
   Fingerprint: D4E8F2A1
   Machine: afeae6a03765a572
   Issued: 20260219213120
```

### 4. Check License Info

```bash
maestro license info
```

Output:
```
📋 License Information:
   Type: PROJECT
   Key: MAESTRO-PROJECT-V1-CMP7F8A3D2E-PRJ4...
   Company: CMP7F8A3D2E
   Project: PRJ4B2C9A1F
   Fingerprint: D4E8F2A1
   Machine ID: afeae6a03765a572
```

---

## License Key Formats

### Company License (Free Tier)
```
MAESTRO-COMPANY-{VERSION}-{COMPANY_ID}-{TIMESTAMP}-{SIGNATURE}

Example:
MAESTRO-COMPANY-V1-CMP7F8A3D2E-20260219143022-A8F3D92E1C4B
```

Components:
- `VERSION`: V1 (format version)
- `COMPANY_ID`: 10-char company identifier
- `TIMESTAMP`: UTC timestamp (YYYYMMDDHHmmss)
- `SIGNATURE`: HMAC-SHA256 truncated to 12 hex chars

### Project License (Paid Tier)
```
MAESTRO-PROJECT-{VERSION}-{COMPANY_ID}-{PROJECT_ID}-{TIMESTAMP}-{FINGERPRINT}-{SIGNATURE}

Example:
MAESTRO-PROJECT-V1-CMP7F8A3D2E-PRJ4B2C9A1F-20260219143500-D4E8F2A1-B7C3E1F9A2D4
```

Components:
- `VERSION`: V1
- `COMPANY_ID`: Parent company ID
- `PROJECT_ID`: 10-char project identifier
- `TIMESTAMP`: UTC timestamp
- `FINGERPRINT`: 8-char hash (machine + slug + path)
- `SIGNATURE`: HMAC-SHA256 truncated to 12 hex chars

---

## Fingerprint Binding

Project licenses are cryptographically bound to:
1. **Machine ID** — stable hardware identifier (UUID on Windows, machine-id on Linux, IOPlatformUUID on macOS)
2. **Project Slug** — normalized project name
3. **Knowledge Store Path** — SHA256 hash of absolute path

**What This Prevents:**
- ❌ Copying knowledge store to different machine
- ❌ Moving knowledge store to different path
- ❌ Sharing ingested data between unlicensed agents

**What This Allows:**
- ✅ Backing up knowledge store (fingerprint persists)
- ✅ Restoring to same machine + path
- ✅ Re-ingesting with new license

---

## Tool Gating Behavior

### Without License

```python
tools = MaestroTools(store_path="knowledge_store")
# Prints: ⚠️  No MAESTRO_LICENSE_KEY found in environment
#         Tools will be disabled.

result = tools.search("waterproofing")
# Returns: "❌ License required to use search.\nSet MAESTRO_LICENSE_KEY..."
```

### With Invalid License

```python
os.environ["MAESTRO_LICENSE_KEY"] = "MAESTRO-PROJECT-V1-INVALID"
tools = MaestroTools(store_path="knowledge_store")
# Prints: ❌ License validation failed: Invalid signature
#         Tools will be disabled.
```

### With Valid License

```python
os.environ["MAESTRO_LICENSE_KEY"] = "MAESTRO-PROJECT-V1-..."  # valid key
tools = MaestroTools(store_path="knowledge_store")
# Validates silently, tools.licensed = True

result = tools.search("waterproofing")
# Returns: [{"type": "material", "match": "waterproofing", ...}]
```

### Skip License Check (Testing)

```python
tools = MaestroTools(store_path="knowledge_store", skip_license_check=True)
# No validation, all tools work
```

---

## Knowledge Store Stamping

After successful ingest with `MAESTRO_LICENSE_KEY` set, a `license.json` is created in the knowledge store:

```json
{
  "license_key_hash": "sha256_hash_of_key",
  "fingerprint": "D4E8F2A1",
  "fingerprint_data": "machine_id:project_slug:store_hash",
  "machine_id": "afeae6a03765a572",
  "project_slug": "my-project",
  "stamped_at": "2026-02-19T21:35:00.123Z",
  "version": "V1"
}
```

On tool initialization, `verify_knowledge_store()` checks:
1. License key hash matches stamped hash
2. Fingerprint matches current machine + slug + path
3. Raises `LicenseError` if mismatch detected

---

## Test Coverage

All 22 tests passing:

**Machine Fingerprinting (6 tests)**
- ✅ Machine ID returns stable 16-char string
- ✅ Fingerprint generation with correct structure
- ✅ Fingerprint stability (same inputs = same output)
- ✅ Fingerprint changes with path/slug

**Company License (5 tests)**
- ✅ Key generation and validation
- ✅ Rejects malformed keys
- ✅ Detects tampered signatures
- ✅ Validates prefix

**Project License (4 tests)**
- ✅ Key generation and validation
- ✅ Fingerprint mismatch detection
- ✅ Tamper detection

**Knowledge Store Stamping (4 tests)**
- ✅ Stamp and verify workflow
- ✅ Missing license file detection
- ✅ Wrong license key rejection
- ✅ Moved knowledge store detection

**License Decorator (3 tests)**
- ✅ Tools disabled without license
- ✅ Tools enabled with valid license
- ✅ Skip check for testing

---

## Security Model

**Threat Model:**
- ✅ Prevents casual copying of knowledge stores
- ✅ Detects tampered license keys (HMAC signature)
- ✅ Binds project licenses to specific hardware + path
- ⚠️ Does NOT prevent determined attackers (secret is hardcoded)
- ⚠️ No online validation or revocation (local-only)

**For Production:**
- Store `MAESTRO_SECRET` server-side only
- Add online validation with viewm4d.com API
- Implement periodic license checks (every 24h)
- Add Stripe webhook integration for revocation
- Use proper key management (env vars, secrets manager)

---

## Next Steps

1. **Production Secret Management:**
   - Move `MAESTRO_SECRET` to server-side environment variable
   - Never commit secrets to git

2. **Online Validation (Optional):**
   - Add `validate_online()` with viewm4d.com API
   - Cache validation results for 24 hours
   - Implement grace period for offline operation

3. **Stripe Integration:**
   - Webhook handlers for subscription events
   - Automatic project provisioning after payment
   - License revocation on cancellation/failure

4. **Frontend Integration:**
   - Display license status in UI
   - Show expiration/renewal prompts
   - Link to billing portal

5. **Documentation:**
   - Update README with license setup instructions
   - Add troubleshooting guide for common errors
   - Document license migration process

---

## Gotchas

1. **Path Sensitivity:** Project licenses bind to **absolute** knowledge store path. Moving the store breaks the fingerprint.

2. **Machine Changes:** Hardware changes (motherboard replacement, VM migration) invalidate fingerprint.

3. **Environment Variables:** `MAESTRO_LICENSE_KEY` must be set in shell/environment, not just .env file (unless tools.py loads dotenv).

4. **Ingest Timing:** License stamping happens AFTER ingest completes. If ingest fails, no stamp is created.

5. **Test Secret:** `MAESTRO_TEST_SECRET_2026` is hardcoded for testing. Replace with server-side secret for production.

---

## Files Reference

```
maestro-ingest/
├── maestro/
│   ├── license.py          # ← Core license module
│   ├── tools.py            # ← Modified: license gating
│   ├── ingest.py           # ← Modified: knowledge store stamping
│   └── cli.py              # ← Modified: license commands
├── tests/
│   └── test_license.py     # ← 22 comprehensive tests
└── LICENSE_SYSTEM.md       # ← Full spec (from Sean)
```

---

**License enforcement is now live!** 🎉

All tools are gated, keys can be generated locally, and knowledge stores are cryptographically stamped.
