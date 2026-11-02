# Component Handoff: GEN-05 — Rendering & Local Artifact Version Implementation

Component ID: **GEN-05**  
Status: **IMPLEMENTED & VERIFIED (Unit / Integration / Subprocess / Restart Crash Matrix / Windows Native / Offline Real SQLite) — Native LibreOffice PDF conversion and visual rasterization checks remain PENDING verification due to absent LibreOffice on workstation**  
Phase: **Phase 1 / P1 (S01–S07 Implemented)**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) §§5–10, G4; [docs/stories/GEN-05.md](../stories/GEN-05.md)  
Prerequisite Handoffs:
- [GEN-01](GEN-01.md) (**VERIFIED**)
- [GEN-02 stories](../stories/GEN-02.md) (**IMPLEMENTED / VERIFIED in `src/job_automation/generation/input_service.py`**)
- [GEN-03](GEN-03.md) (**IMPLEMENTED / VERIFIED**)
- [GEN-04](GEN-04.md) (**IMPLEMENTED / VERIFIED in `src/job_automation/generation/validation_service.py`**)
- [DATA-01](DATA-01.md) (**VERIFIED storage and migrations**)  
Date Completed: 31 October 2026  
Direct Covered Requirements: [R11](../../IMPLEMENTATION_BLUEPRINT.md#r11), [R12](../../IMPLEMENTATION_BLUEPRINT.md#r12), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14)  
Supporting Constraints: [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)

---

## 1. Executive Summary & Component Scope

`GEN-05` transforms factually and structurally validated C14 v2 drafts (`DraftDocumentV2`, schema 2.0) into readable, editable Microsoft Word (`.docx`) and matching PDF (`.pdf`) documents using approved, versioned local layouts. It ensures that physical artifact bytes are generated in isolated staging directories, strictly verified before promotion, and published atomically into durable managed storage.

### Core Architecture & Behavioral Invariants

1. **Strict Gate Enforcement (ValidatedDraftForRendering)**:
   - Physical rendering is only authorized when the upstream `GEN-04` validation report has `render_decision == "allowed_for_review"` and `fatal_count == 0`.
   - Any draft that is unvalidated, has fatal errors, or has a mismatched content hash is blocked before any rendering execution or layout pinning.
2. **Approved Layout Catalog & Immutable Pinning**:
   - Approved layout definitions (`ApprovedLayout`, schema 1.0) define margins, typography, page setup, header/footer draft notices, and supported content specifications (`content-basic`, `content-compact`).
   - At first render intent, the resolved layout is pinned as an immutable JSON snapshot at `pinned_layouts/<request_id>/<layout_id>_<version>.json`. Retries reuse the pinned layout even if catalog defaults change.
3. **Editable DOCX Projection (`python-docx`)**:
   - Exact ordered section, entry, claim, and subjective block projection.
   - Dynamic page numbering (`Seite X von Y`) in footers.
   - Draft review banner (`[Entwurf – vor Verwendung prüfen]` / `[Draft – review before use]`) in headers.
   - Strict candidate identity omission handling (`candidate_name` remains `None` without inventing personal details).
   - Metadata sanitization (clears author, company, comments) and invalid XML control character filtering.
   - Comprehensive OOXML verification (`verify_docx_file`): validates ZIP CRC-32 integrity, core relationships, `word/document.xml`, reopens via `docx.Document`, and confirms complete textual coverage of headings and claims.
4. **Process Isolation & PDF Conversion (`LibreOfficeConverter`)**:
   - Headless LibreOffice converter (`soffice.com`) invoked via `run_bounded_process` with `shell=False`.
   - Completely isolated user profile URI: `-env:UserInstallation=<uri>` using `Path.as_uri()` for Windows paths with spaces and umlauts.
   - Native Windows process tree termination via `taskkill /F /T /PID` on timeout (120s limit).
   - Independent PDF verification (`verify_pdf_file` via `pypdf`): checks `%PDF-` signature, encryption status, positive page count, and textual claim coverage.
5. **Atomic Promotion & Crash-Safe Publication (Migration 014)**:
   - Staging under `<data_root>/staging/render/{attempt_id}/`.
   - Atomic filesystem move (`shutil.move`) to `<data_root>/artifacts/{request_id}/v0001/{artifact_id}.{fmt}`.
   - Atomic SQLite compound transaction: persists `rendered_artifact_receipts`, C14 `artifacts`, and `generation_artifact_deliveries` slot pointers together.
   - Commits `artifact_sets` table; subsequent retries reopen and verify exact bytes via `reopen_and_verify_set` without re-rendering or converting anew.
6. **Delivery & Approval Invariants**:
   - Approval status remains strictly `draft` (`DocumentApproval.DRAFT`). No documents are marked approved.
   - Delivery status remains strictly `local_only` (`delivery_status="local_only"`). No remote Salesforce Files uploads are performed (owned by `GEN-06`).

---

## 2. Architecture & Module Overview

### Module Inventory

| Module | Purpose |
|---|---|
| `src/job_automation/generation/render_records.py` | Core contracts: `PageSetup`, `TypographySetup`, `ApprovedLayout`, `RenderSpecification`, `RenderIntent`, `RenderAttempt`, `RenderedArtifactReceipt`, `ArtifactSet`, `LocalRenderResult`, plus JSON schema exporter. |
| `src/job_automation/generation/render_ports.py` | Port protocol `DocumentRendererServicePort` (`render_or_reopen`, `reopen_artifact_set`). |
| `src/job_automation/generation/render_settings.py` | `RenderingSettings`: configuration for timeouts, allowed fonts, minimum font sizes, and converter paths. |
| `src/job_automation/generation/layout_catalog.py` | `LayoutCatalog`: standard A4 layouts (`LAYOUT_CV_BASIC_A4`, `LAYOUT_CV_COMPACT_A4`, `LAYOUT_LETTER_BASIC_A4`, `LAYOUT_LETTER_COMPACT_A4`) and immutable pinning under `pinned_layouts/<request_id>/`. |
| `src/job_automation/generation/render_projection.py` | `project_draft_to_docx`: semantic paragraph/entry/claim styling, table/bullet formatting, and header/footer draft notice generation. |
| `src/job_automation/generation/render_checks.py` | `verify_docx_file`: OOXML ZIP parts verification, reopen, and textual claim coverage validation. |
| `src/job_automation/generation/render_process.py` | `run_bounded_process`: timeout execution with native Windows process tree termination (`taskkill`). |
| `src/job_automation/generation/pdf_checks.py` | `verify_pdf_file`: PDF header, encryption, page count, and textual content verification via `pypdf`. |
| `src/job_automation/generation/docx_renderer.py` | `DocxRenderer`: DOCX builder and verification runner. |
| `src/job_automation/generation/libreoffice_converter.py` | `LibreOfficeConverter`: headless LibreOffice converter with isolated profile and fresh attempt directories. |
| `src/job_automation/generation/render_service.py` | `RenderService`: end-to-end rendering coordinator managing gate checks, staging, conversion, promotion, and set commitment. |
| `src/job_automation/generation/render_adapter.py` | `DocumentRendererAdapter`: adapter implementing `DocumentRenderer` protocol for `GenerationCoordinator` (GEN-01). |
| `src/job_automation/storage/repositories/render_artifacts.py` | `RenderArtifactRepository`: SQLite repository for intents, attempts, receipts, compound saves, and on-disk verification. |
| `src/job_automation/storage/migrations.py` | `MIGRATION_014_RENDER_ARTIFACTS`: forward migration creating render tables and indices. |

### Storage Schema (Migration 014)

```sql
CREATE TABLE IF NOT EXISTS render_intents (
    intent_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    logical_key TEXT NOT NULL UNIQUE,
    spec_hash TEXT NOT NULL,
    artifact_version INTEGER NOT NULL DEFAULT 1,
    target_formats_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS render_attempts (
    attempt_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES render_intents(intent_id) ON DELETE CASCADE,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    attempt_number INTEGER NOT NULL,
    format TEXT NOT NULL,
    staging_dir TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    exit_code INTEGER,
    duration_ms INTEGER,
    error_json TEXT
);

CREATE TABLE IF NOT EXISTS rendered_artifact_receipts (
    receipt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    artifact_id TEXT NOT NULL UNIQUE,
    artifact_set_id TEXT NOT NULL,
    format TEXT NOT NULL,
    version INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    local_path TEXT NOT NULL,
    relative_managed_path TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    draft_hash TEXT NOT NULL,
    report_hash TEXT NOT NULL,
    layout_digest TEXT NOT NULL,
    docx_artifact_id TEXT,
    docx_content_hash TEXT,
    output_checks_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    UNIQUE(request_id, version, format)
);

CREATE TABLE IF NOT EXISTS artifact_sets (
    set_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    set_version INTEGER NOT NULL,
    required_formats_json TEXT NOT NULL,
    is_complete INTEGER NOT NULL DEFAULT 0,
    report_id TEXT NOT NULL,
    report_hash TEXT NOT NULL,
    draft_hash TEXT NOT NULL,
    set_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(request_id, set_version)
);
```

---

## 3. Installation & Configuration Instructions

### Python Environment Dependencies

The component requires Python 3.12+ with the following pinned packages installed in `.venv`:

```powershell
& .venv\Scripts\python.exe -m pip install "python-docx==1.2.0" "pypdf==5.9.0" "lxml==6.1.3"
```

These dependencies are recorded in `pyproject.toml` under `project.dependencies`.

### LibreOffice Installation & Configuration

For PDF conversion, LibreOffice (desktop console executable `soffice.com`) is required:

1. **Default Discovery**: Checks standard 64-bit and 32-bit Program Files directories:
   - `C:\Program Files\LibreOffice\program\soffice.com`
   - `C:\Program Files (x86)\LibreOffice\program\soffice.com`
2. **Explicit Configuration**: Can be configured via `RenderingSettings(libreoffice_path=Path("..."))` or in application JSON settings under `rendering.libreoffice_path`.
3. **Current Workstation State**: LibreOffice is **not installed** on this Windows environment.
   - Per GEN-05 specification and graceful degradation rules, when LibreOffice is absent:
     - `DocxRenderer` generates and verifies DOCX output completely.
     - PDF conversion attempt records a classified failure (`error_json` with code `renderer_missing` and category `missing_configuration`).
     - Staged DOCX is preserved, and the system does not crash or corrupt state.
     - Native LibreOffice PDF conversion and visual rasterization checks remain reported as **PENDING verification**.

---

## 4. Approved Layout Catalog & Versioning

Four approved baseline layouts (schema version 1.0) are registered in `LayoutCatalog`:

| Layout ID | Version | Type | Language | Margins (T/B/L/R mm) | Primary Font / Body Size | Notes |
|---|---|---|---|---|---|---|
| `layout-cv-basic-a4` | `1.0.0` | CV | `de`, `en` | 25 / 20 / 25 / 20 | Calibri 11.0 pt | Standard DIN A4 single-column CV |
| `layout-cv-compact-a4` | `1.0.0` | CV | `de`, `en` | 20 / 18 / 20 / 18 | Calibri 10.0 pt | Dense A4 CV with 10pt body text |
| `layout-letter-basic-a4` | `1.0.0` | Cover Letter | `de`, `en` | 25 / 20 / 25 / 20 | Calibri 11.0 pt | DIN 5008-compatible cover letter layout |
| `layout-letter-compact-a4` | `1.0.0` | Cover Letter | `de`, `en` | 20 / 18 / 20 / 18 | Calibri 10.5 pt | Compact cover letter layout |

All layouts specify standard fallback fonts (`Arial`, `Liberation Sans`, `DejaVu Sans`), line spacing (`1.1` to `1.2`), and draft notice strings:
- German (`de`): `"Entwurf – vor Verwendung prüfen"`
- English (`en`): `"Draft – review before use"`

Layout pinning produces an immutable digest of all layout properties, ensuring that any subsequent modification requires an explicit new layout version and approval record.

---

## 5. Verification & Test Evidence

### Full Repository Regression Run

```powershell
& .venv\Scripts\python.exe -m pytest -q
```
**Outcome**: **1,643 passed in 63.57s (0 failed)** across all unit, contract, integration, storage, operations, and generation test suites.

### GEN-05 Rendering Test Suite (35 tests)

```powershell
& .venv\Scripts\python.exe -m pytest tests\generation\rendering\ -v
```
**Outcome**: **35 passed in 7.92s**:
- `test_contracts.py` (6 passed): validates layout, render spec, intent, attempt, receipt, artifact set, and JSON schema exports.
- `test_layout_catalog.py` (3 passed): catalog discovery, compatibility filtering, and layout pinning immutability.
- `test_docx_renderer.py` (4 passed): German Unicode characters (`äöü ÄÖÜ ß`, `€`, `„...“`, `–`), 1,200+ character bullets across page splits, safe XML escaping, and corrupt ZIP detection.
- `test_pdf_checks.py` (3 passed): missing files, corrupt signatures, unreadable text.
- `test_libreoffice_converter.py` (4 passed): missing executable (`renderer_missing`), process timeout classification, nonzero exit handling, zero exit without output.
- `test_artifact_store.py` (5 passed): migration 014, intent lifecycle, attempt audit logging, compound receipt/artifact save, and on-disk corruption/deletion detection.
- `test_render_service.py` (6 passed): standard DOCX render, idempotent set reuse without re-rendering, validation gate blocking, unsupported language blocking, missing LibreOffice handling, and disk tampering detection.
- `test_coordinator_rendering.py` (2 passed): end-to-end coordinator stage 4 rendering, delivery slot creation, request transition to `UPLOAD_PENDING`, and gate blocking on denied validation.
- `test_windows_paths.py` (1 passed): execution in paths with spaces and German umlauts (`Bewerbung Prüfung äöü ÄÖÜ ß\Unterlagen Größe`).
- `test_windows_restart.py` (1 passed): cross-process crash recovery and set reopening across distinct Python processes.

### Manual Smoke Test Execution

```powershell
& .venv\Scripts\python.exe tests\manual\gen05_render_smoke.py
```
**Output**:
```text
=== GEN-05 Rendering Smoke Test ===
Rendering CV (ID: 78426afd-baa9-4a73-bb38-2abf8cd07ed1)...
  -> CV DOCX rendered successfully:
     Path: ...\tmp\manual_smoke_gen05\artifacts\78426afd-baa9-4a73-bb38-2abf8cd07ed1\v0001\dcb08fa9-efb2-42e8-b7e4-c6f007a194e5.docx
     Size: 38034 bytes
     SHA256: sha256:e89e08ea97d2f89c4eb4034f73173c75054f5cd909c934bec6f77864cce60971
Rendering Cover Letter (ID: 3a96eabe-b2e5-4b33-8707-027f98f1084b)...
  -> Letter DOCX rendered successfully:
     Path: ...\tmp\manual_smoke_gen05\artifacts\3a96eabe-b2e5-4b33-8707-027f98f1084b\v0001\e5fc0dac-bbea-4e9c-bf22-39ef3b788216.docx
     Size: 37668 bytes
     SHA256: sha256:3873785b95a85d380f504c65433b23db9536424d5a786ca3409356bf8bde12c4

=== LibreOffice / PDF Conversion Status ===
  [NOT INSTALLED] LibreOffice executable (soffice.com) not found on host machine.
  Status: Native LibreOffice PDF conversion and visual rasterization checks remain PENDING.
  Per GEN-05 specification: PDF conversion degrades gracefully with error 'renderer_missing'.

=== Contract Invariant Check ===
  [CONFIRMED] Delivery status: 'local_only' (No remote uploads performed)
  [CONFIRMED] Approval status: 'draft' (No documents marked approved)
  [CONFIRMED] Output files verified via ZIP / OOXML inspection & reopened
=== Smoke Test Finished Successfully ===
```

---

## 6. Rendering Limitations & Downstream Delivery Handoff (GEN-06)

### Explicit Rendering Limitations

1. **Host Environment (LibreOffice Missing)**:
   - LibreOffice is not installed on the current workstation.
   - Headless PDF conversion and native visual page rasterization checks remain **PENDING verification** on an environment where LibreOffice is installed.
   - The DOCX generation pipeline, layout catalog, output verification, atomic promotion, and retry persistence are fully implemented, verified, and operational.
2. **Layout Pagination Variance**:
   - Different word processing engines (Microsoft Word vs. LibreOffice Writer) can paginate DOCX content with slight geometrical variances. The rendered PDF represents the frozen pagination of the specific converter environment used.
3. **No Automatic Truth or Approval Certification**:
   - The produced documents carry visible draft banners (`[Entwurf – vor Verwendung prüfen]`).
   - Rendering does not certify factual truth or entailment; human review remains mandatory before document approval or submission.

### Downstream Handoff to GEN-06

- `GEN-05` provides durable physical files at `<data_root>/artifacts/<request_id>/v0001/<artifact_id>.<fmt>`, paired with committed `RenderedArtifactReceipt` rows and C14 `Artifact` metadata with `delivery_status="local_only"` and `approval_status=DocumentApproval.DRAFT`.
- `GEN-06` is responsible for:
  - Reading the committed `ArtifactDeliveryRecord` pointers.
  - Uploading physical bytes to Salesforce Files (`ContentVersion` / `ContentDocumentLink`).
  - Handling upload retry and ambiguous upload reconciliation.
  - Updating `delivery_status` to `"delivered"` and setting `remote_file_id`.
  - Presenting documents for candidate and recruiter review.

