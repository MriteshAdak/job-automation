# Component Handoff: SFCLIENT-01 — Salesforce Authentication and Gateway

Component ID: **SFCLIENT-01**  
Status: **VERIFIED (Offline / Contract / Fake-Transport) — Live acceptance pending SF-02 authorization handoff**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), especially §§4–6 and §§8–10  
Prerequisite Handoffs:
- [FND-01](FND-01.md) (**VERIFIED**)
- **SF-02** (**ABSENT / PENDING PREREQUISITE**)  
Planning Reference: [docs/stories/SFCLIENT-01.md](../stories/SFCLIENT-01.md)  
Date Completed: 29 October 2026  
Direct Covered Requirements: [R08](../../IMPLEMENTATION_BLUEPRINT.md#r08), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)  

---

## 1. Prerequisites and SF-02 Verification Report

Before implementing the gateway, repository assets, configuration, and upstream component handoffs were inspected:

| Prerequisite / Evidence | Found In Repository | Verification Status | Consequence for SFCLIENT-01 |
|---|---|---|---|
| **FND-01 Contracts & Base** | `docs/components/FND-01.md`, `src/job_automation/contracts/` | **VERIFIED** | Reused `ContractModel` (`frozen=True`, `extra="forbid"`, `schema_version="1.0"`), `ClassifiedError`, `ErrorCategory`, `AppConfig` loader, and deterministic schema exporter discipline. |
| **Legacy SalesforceGateway** | `src/job_automation/contracts/interfaces.py` | **VERIFIED** | `execute_sync(SyncOperation)` preserved intact as legacy domain-sync boundary. Conformance by `FakeSalesforceGateway` remains 100% valid. |
| **C12 SyncOperation** | `src/job_automation/contracts/sync.py` | **VERIFIED** | SFCLIENT-01 does **not** consume or mutate C12 outbox state, calculate fingerprints, or order publications (owned by `SYNC-01`). |
| **SF-02 Handoff & Org Assets** | `docs/components/SF-02.md`, `docs/stories/SF-02.md` | **ABSENT** | **Missing prerequisite**. No Connected App / External Client App registration, OAuth credentials, certificates, approved scopes, or permission sets exist in the repository. |
| **Salesforce Org Configuration** | Environment & repository | **UNCONFIGURED** | Org ID, approved user identity, and actual metadata package (`Job__c`, `Company__c`) are not configured in runtime environment or repository. |

### Missing Prerequisites Statement
As mandated by the user request and `docs/stories/SFCLIENT-01.md`:
1. **SF-02 is NOT implemented here.** SFCLIENT-01 does not create Connected Apps, deploy metadata, generate self-signed certificates, or configure OAuth scopes in Salesforce.
2. Missing OAuth credentials and org settings yield actionable `ErrorCategory.MISSING_CONFIGURATION` errors before initiating network I/O or token requests.
3. Offline, contract, fake-transport, and native Windows DPAPI test suites are fully implemented and verified (62/62 tests passing). Live production authentication and live record acceptance remain pending until the owner provides the completed SF-02 handoff and credentials.

---

## 2. Implementation Status by Story

All stories planned under `docs/stories/SFCLIENT-01.md` are implemented:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **SFCLIENT-01-S01** | Freeze gateway contracts & boundaries | **VERIFIED** | Established `src/job_automation/contracts/salesforce.py` with typed request/result models, `SalesforceGatewayV2` Protocol in `interfaces.py`, `GatewayResult[T]` exclusivity validation, bounded JSON constraints, and exported 61 schemas under `schemas/v1/`. |
| **SFCLIENT-01-S02** | Configure API & enforce bounded HTTPS | **VERIFIED** | Implemented `SalesforceSettings` in `salesforce/configuration.py` with strict HTTPS validation, explicit `vNN.0` API versioning, `approved_origins` allowlisting, `UrllibHttpTransport` with automatic redirects disabled, and `salesforce_settings_ref` in `AppConfig`. |
| **SFCLIENT-01-S03** | Protected credential lifecycle & token sessions | **VERIFIED** | Implemented `WindowsDpapiCredentialStore` using native Windows DPAPI (`CryptProtectData`/`CryptUnprotectData`), `InMemoryCredentialStore`, `OAuthTokenProvider` with in-memory session caching, single 401 renewal, atomic refresh token rotation, and single-use exchange marker protection. |
| **SFCLIENT-01-S04** | Typed reads & caller-mapped mutations | **VERIFIED** | Implemented `SalesforceGatewayV2Client` in `salesforce/gateway.py` with `check_connection`, `get_limits`, `describe_object`, `get_record`, `query_page` (with hostile continuation protection), `upsert_by_external_id` (201/200/204), and `update_record` (204). Caller fields preserved verbatim without domain defaults. |
| **SFCLIENT-01-S05** | Error classification & bounded recovery | **VERIFIED** | Implemented `salesforce/errors.py`, `salesforce/budget.py`, and `salesforce/retry.py`. Quota precedence enforced (403 `REQUEST_LIMIT_EXCEEDED` is `rate_limit`, not permission). Ambiguous writes default strictly to NO REPLAY (`remote_outcome=unknown`, `recovery_action=reconcile`) unless `replay_safe=True`. Unified call budget enforced (max 6 total sends, max 3 resource, max 2 token, 60s deadline). |
| **SFCLIENT-01-S06** | Secret-safe diagnostics & recorder isolation | **VERIFIED** | Implemented `salesforce/diagnostics.py` with `redact_sensitive_text` scrubbing Bearer tokens, secrets, URL query parameters, and private keys. Allowlisted diagnostic events (`DiagnosticEvent`) capture only safe codes, counts, and timings without payloads or queries. Recorder exceptions isolated. |
| **SFCLIENT-01-S07** | Native Windows verification & smoke script | **VERIFIED** | Implemented `tests/manual/salesforce_smoke.py` with read-only default and strict `--allow-write` + `SYNTHETIC_TEST_` prefix guards. Verified DPAPI and path resolution on native Windows with spaces and German umlauts (`Job Automation Prüfung ä`). |

---

## 3. Files Changed and Contracts Established

### New Source Files (`src/job_automation/salesforce/`)
- [`contracts/salesforce.py`](../../src/job_automation/contracts/salesforce.py): Versioned models for gateway operations, `GatewayResult[T]`, `GatewayFailure`, `AttemptSummary`, `OperationKind`, `RemoteOutcome`, `RecoveryAction`, and typed requests/results for 7 operations.
- [`salesforce/__init__.py`](../../src/job_automation/salesforce/__init__.py): Public package exports.
- [`salesforce/ports.py`](../../src/job_automation/salesforce/ports.py): Protocols for `HttpTransport`, `CredentialStore`, `TokenProvider`, `Clock`, `Sleeper`, `Jitter`, and `SafeDiagnosticsRecorder`.
- [`salesforce/configuration.py`](../../src/job_automation/salesforce/configuration.py): `SalesforceSettings`, `validate_https_url`, `normalize_api_version`, and loader.
- [`salesforce/transport.py`](../../src/job_automation/salesforce/transport.py): `UrllibHttpTransport` with `_NoRedirectHandler`, TLS validation, byte ceilings, and `uncertain_transmission` tracking.
- [`salesforce/credentials.py`](../../src/job_automation/salesforce/credentials.py): `WindowsDpapiCredentialStore` (native DPAPI) and `InMemoryCredentialStore`.
- [`salesforce/auth.py`](../../src/job_automation/salesforce/auth.py): `OAuthTokenProvider` implementing session caching, single renewal, atomic rotation, and interrupted exchange protection.
- [`salesforce/serialization.py`](../../src/job_automation/salesforce/serialization.py): JSON serialization, URL percent-encoding, continuation path validation, and response envelope parsers.
- [`salesforce/errors.py`](../../src/job_automation/salesforce/errors.py): Classification table, allowlisted provider error codes, quota precedence, and `GatewayFailure` mapper.
- [`salesforce/budget.py`](../../src/job_automation/salesforce/budget.py): `CallBudget` tracking total sends, resource sends, token sends, and monotonic deadline.
- [`salesforce/retry.py`](../../src/job_automation/salesforce/retry.py): `parse_retry_after`, `calculate_backoff_delay`, and `is_replay_allowed`.
- [`salesforce/diagnostics.py`](../../src/job_automation/salesforce/diagnostics.py): `redact_sensitive_text` and `SafeMemoryDiagnosticsRecorder`.
- [`salesforce/gateway.py`](../../src/job_automation/salesforce/gateway.py): Production `SalesforceGatewayV2Client`.

### Modified Upstream Files
- [`src/job_automation/contracts/interfaces.py`](../../src/job_automation/contracts/interfaces.py): Added `SalesforceGatewayV2` Protocol while keeping legacy `SalesforceGateway` unchanged.
- [`src/job_automation/contracts/export_schemas.py`](../../src/job_automation/contracts/export_schemas.py): Registered Salesforce models in `CONTRACT_MODELS` and exported 61 schemas.
- [`src/job_automation/configuration.py`](../../src/job_automation/configuration.py): Added `salesforce_settings_ref` to `AppConfig` and `salesforce_settings_path` to `ResolvedPaths`.

### Configuration and Schema Files
- [`config/salesforce.example.json`](../../config/salesforce.example.json): Non-secret example configuration.
- [`schemas/v1/`](../../schemas/v1/): 19 new JSON Schemas for Salesforce contract models.

### Test and Smoke Files
- [`tests/fakes/salesforce_transport.py`](../../tests/fakes/salesforce_transport.py): Scripted in-memory HTTP transport.
- [`tests/fixtures/salesforce/`](../../tests/fixtures/salesforce/): Positive and negative synthetic fixtures.
- [`tests/manual/salesforce_smoke.py`](../../tests/manual/salesforce_smoke.py): Safe-by-default manual smoke script.
- [`tests/salesforce/`](../../tests/salesforce/): 12 test modules covering contracts, config, transport, credentials, auth, reads, mutations, error classification, retries/budgets, diagnostics, smoke guards, and Windows paths.

---

## 4. Public Gateway Interface (`SalesforceGatewayV2`)

```python
@runtime_checkable
class SalesforceGatewayV2(Protocol):
    """Boundary 8 (V2): Typed, versioned Salesforce REST gateway (SFCLIENT-01)."""

    def check_connection(
        self, request: ConnectionCheckRequest
    ) -> GatewayResult[ConnectionCheckResult]: ...

    def get_limits(
        self, request: LimitsRequest
    ) -> GatewayResult[LimitsResult]: ...

    def describe_object(
        self, request: DescribeObjectRequest
    ) -> GatewayResult[DescribeObjectResult]: ...

    def get_record(
        self, request: GetRecordRequest
    ) -> GatewayResult[GetRecordResult]: ...

    def query_page(
        self, request: QueryPageRequest
    ) -> GatewayResult[QueryPageResult]: ...

    def upsert_by_external_id(
        self, request: UpsertRequest
    ) -> GatewayResult[UpsertResult]: ...

    def update_record(
        self, request: UpdateRequest
    ) -> GatewayResult[UpdateResult]: ...
```

### Result Exclusivity Envelope
Every operation returns `GatewayResult[T]` which guarantees:
- `is_success == True`: `value` contains typed result, `failure` is `None`.
- `is_failure == True`: `failure` contains `GatewayFailure`, `value` is `None`.
- Both `value` and `failure` simultaneously, or neither, is rejected with a `ValueError`.
- `GatewayFailure` provides:
  - `error: ClassifiedError` (system error category and safe message)
  - `safe_provider_code: str | None` (allowlisted provider code, e.g. `REQUEST_LIMIT_EXCEEDED`, `INVALID_SESSION_ID`)
  - `http_status: int | None`
  - `operation_kind: OperationKind`
  - `remote_outcome: RemoteOutcome` (`not_sent`, `rejected`, `unknown`, `acknowledged`)
  - `recovery_action: RecoveryAction` (`none`, `retry_later`, `reauthorize`, `reconcile`, `fix_configuration`)
  - `retry_not_before: UtcDatetime | None` (from server `Retry-After`)
  - `exhausted_budget: bool`
  - `attempts: list[AttemptSummary]`

---

## 5. Non-Secret Configuration Model (`SalesforceSettings`)

Configuration is strictly secret-free, referencing Windows DPAPI-protected credentials via opaque string references:

```json
{
  "schema_version": "1.0",
  "instance_url": "https://example-dev-ed.develop.my.salesforce.com",
  "api_version": "v60.0",
  "auth_flow": "refresh_token",
  "client_id_ref": "salesforce/client_id",
  "credential_ref": "salesforce/refresh_token",
  "token_url": "https://login.salesforce.com/services/oauth2/token",
  "expected_org_id": "00D000000000001",
  "connect_timeout_seconds": 10.0,
  "read_timeout_seconds": 20.0,
  "total_call_timeout_seconds": 60.0,
  "max_total_sends": 6,
  "max_resource_sends": 3,
  "max_token_sends": 2,
  "initial_backoff_seconds": 1.0,
  "max_backoff_seconds": 8.0,
  "max_response_bytes": 10485760
}
```

---

## 6. Commands and Test Results

### Test Execution Commands
Executed from repository root on native Windows in PowerShell:

```powershell
# 1. Salesforce unit, contract, and fake transport test suite
& ".\.venv\Scripts\python.exe" -m pytest tests\salesforce tests\contracts\test_interfaces.py tests\contracts\test_work_records.py tests\test_configuration.py tests\test_cli.py

# 2. Config check with native Windows Unicode and space path
& ".\.venv\Scripts\python.exe" -m job_automation config check --config ".\config\app.example.json" --data-root (Join-Path $env:LOCALAPPDATA "Job Automation Prüfung ä")

# 3. Manual smoke verification script (read-only default, reports prerequisite status)
& ".\.venv\Scripts\python.exe" ".\tests\manual\salesforce_smoke.py" --config (Join-Path $env:LOCALAPPDATA "Job Automation Prüfung ä\app.json")

# 4. Complete repository test suite
& ".\.venv\Scripts\python.exe" -m pytest
```

### Test Results Summary
- `tests/salesforce/`: **62 passed in 0.58s**
- Complete Test Suite: **1122 passed in 14.70s** with 0 errors and 0 warnings.
- `config check`: **VALID** (exit code 0).
- `salesforce_smoke.py`: Exited with code 0 reporting `[PREREQUISITE STATUS] PENDING: No configuration file provided. (SF-02 handoff absent)`.

---

## 7. Native Windows Verification Status

All native Windows constraints ([R14](../../IMPLEMENTATION_BLUEPRINT.md#r14)) were verified directly on Windows 11 / Python 3.12:

| Scenario | Test Target | Result | Notes |
|---|---|---|---|
| **DPAPI Encryption & Decryption** | `ctypes.windll.crypt32.CryptProtectData` / `CryptUnprotectData` | **PASSED** | Bytes encrypted on disk; plaintext does not appear in storage file; decrypted output matches original. |
| **Unicode & Spaces in Paths** | `Job Automation Prüfung ä\Benutzer Daten\credentials` | **PASSED** | Windows paths with umlauts, spaces, and nested subdirectories resolve and persist cleanly. |
| **Working Directory Independence** | Executed from `$env:TEMP` / `$tmp_path` | **PASSED** | Credential and configuration resolution unaffected by active working directory. |
| **Process Restart Simulation** | Fresh `WindowsDpapiCredentialStore` instance on existing directory | **PASSED** | Re-opened store decrypts previously stored credential without state loss. |
| **Safe Smoke Guards** | `tests/manual/salesforce_smoke.py` | **PASSED** | Read-only by default; write mode strictly blocked without `--allow-write` and `SYNTHETIC_TEST_` key prefix. |

---

## 8. Known Limitations and Guidance for Dependent Components

1. **SF-02 Integration Authorization**:
   - Production OAuth flow and live org credentials remain unconfigured until the owner executes SF-02.
   - When configured, `WindowsDpapiCredentialStore` will store the approved refresh token and client ID beneath `data_root / "credentials"`.
2. **Domain Mapping & Publication Selection (SYNC-01)**:
   - SFCLIENT-01 does **not** map `SyncPayload` fields to `Job__c` columns or select which jobs to push.
   - SYNC-01 will consume `SalesforceGatewayV2.upsert_by_external_id` and handle outbox atomicity (`atomic_commit_assessment_and_sync`).
3. **Replay Policy for Mutations**:
   - `update_record` never retries after uncertain transmission.
   - `upsert_by_external_id` only retries when caller explicitly sets `replay_safe=True`.
4. **File Delivery (GEN-06)**:
   - Attachment delivery (Salesforce `ContentVersion` / `ContentDocumentLink`) belongs to **GEN-06**. SFCLIENT-01 provides the transport foundation.

