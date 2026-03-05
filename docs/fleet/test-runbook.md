# Fleet Test Runbook

This runbook executes the matrix in `docs/fleet/test-matrix.md` with reproducible commands and evidence capture.

## 1) Test Harness Setup

```bash
export MATRIX_ROOT="$HOME/Desktop/fleet_matrix"
export MATRIX_EVIDENCE="$MATRIX_ROOT/evidence"
mkdir -p "$MATRIX_EVIDENCE"
```

Recommended: isolate each test with a dedicated OpenClaw profile + Fleet store.

```bash
export MAESTRO_OPENCLAW_PROFILE="maestro-fleet-matrix"
export MATRIX_STORE="$MATRIX_ROOT/store"
mkdir -p "$MATRIX_STORE"
```

## 2) Production Install + Deploy Commands

Installer (customer path):

```bash
curl -fsSL https://get.maestro.run/fleet | bash
```

Deploy (interactive):

```bash
maestro-fleet deploy
```

Deploy (non-interactive baseline, no initial project maestro):

```bash
maestro-fleet deploy \
  --company-name "Matrix Co" \
  --commander-model "anthropic/claude-opus-4-6" \
  --project-model "anthropic/claude-opus-4-6" \
  --gemini-api-key "$GEMINI_API_KEY" \
  --openai-api-key "$OPENAI_API_KEY" \
  --anthropic-api-key "$ANTHROPIC_API_KEY" \
  --telegram-token "$COMMANDER_TELEGRAM_TOKEN" \
  --non-interactive \
  --skip-remote-validation \
  --local \
  --store "$MATRIX_STORE"
```

## 3) A1 Procedure (Commander-Only Baseline)

1. Set isolated profile/store:

```bash
export MAESTRO_OPENCLAW_PROFILE="maestro-fleet-a1"
export A1_STORE="$MATRIX_ROOT/a1/store"
mkdir -p "$A1_STORE"
```

2. Run deploy without any `--project-*` flags:

```bash
maestro-fleet deploy \
  --company-name "Matrix A1" \
  --commander-model "anthropic/claude-opus-4-6" \
  --project-model "anthropic/claude-opus-4-6" \
  --gemini-api-key "$GEMINI_API_KEY" \
  --openai-api-key "$OPENAI_API_KEY" \
  --anthropic-api-key "$ANTHROPIC_API_KEY" \
  --telegram-token "$COMMANDER_TELEGRAM_TOKEN" \
  --non-interactive \
  --skip-remote-validation \
  --local \
  --store "$A1_STORE"
```

3. Capture evidence:

```bash
maestro-fleet status | tee "$MATRIX_EVIDENCE/a1-status.txt"
maestro-fleet doctor --json --store "$A1_STORE" | tee "$MATRIX_EVIDENCE/a1-doctor.json"
openclaw --profile "$MAESTRO_OPENCLAW_PROFILE" inspect config > "$MATRIX_EVIDENCE/a1-openclaw-config.json"
curl -fsS http://localhost:3000/api/command-center/state | tee "$MATRIX_EVIDENCE/a1-command-center-state.json"
```

4. Assert commander-only:

```bash
jq '[.agents.list[] | select(.id=="maestro-company")] | length' "$MATRIX_EVIDENCE/a1-openclaw-config.json"
jq '[.agents.list[] | select((.id | tostring | startswith("maestro-project-")))] | length' "$MATRIX_EVIDENCE/a1-openclaw-config.json"
```

Expected:
- Commander count = `1`
- Project-maestro count = `0`

## 4) Result Recording Template

Create one result file per test (`$MATRIX_EVIDENCE/<id>-result.md`):

```md
# <TEST_ID> Result
- Status: PASS | PARTIAL | FAIL
- Date:
- Profile:
- Store:
- Command(s):
- Evidence files:
- Notes:
- Defects:
```

## 5) Next Recommended Sequence

1. `A2` runtime/API consistency checks
2. `A4/A5` project maestro provisioning + isolation
3. `A6` ingest smoke (2-page subset) and then controlled expansion
4. `R1/R2` idempotency + restart recovery
