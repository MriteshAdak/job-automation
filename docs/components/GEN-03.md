# Component Handoff: GEN-03 — Draft Content Generation (CV and Cover Letter)

Component ID: **GEN-03**  
Status: **IMPLEMENTED & VERIFIED (Unit / Integration / Subprocess / Restart Crash Matrix / Windows Native / Offline Scripted Provider) — Live model quality evaluation pending MODEL-01 local runtime execution & human semantic review**  
Phase: **Phase 1 / P1 (S01–S07 Implemented)**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) §§4–9, G4; [docs/stories/GEN-03.md](../stories/GEN-03.md)  
Prerequisite Handoffs:
- [GEN-01](GEN-01.md) (**VERIFIED**)
- [GEN-02 stories](../stories/GEN-02.md) (**IMPLEMENTED / VERIFIED in `src/job_automation/generation/input_service.py`**)
- [LLM-01](LLM-01.md) (**VERIFIED**)
- [CONTEXT-01](CONTEXT-01.md) through [CONTEXT-04](CONTEXT-04.md) (**VERIFIED**)
- [PROFILE-01](PROFILE-01.md) (**VERIFIED**)  
Date Completed: 31 October 2026  
Direct Covered Requirements: [R11](../../IMPLEMENTATION_BLUEPRINT.md#r11), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15)  
Supporting Constraints: [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06), [R07](../../IMPLEMENTATION_BLUEPRINT.md#r07), [R10](../../IMPLEMENTATION_BLUEPRINT.md#r10), [R12](../../IMPLEMENTATION_BLUEPRINT.md#r12), [R13](../../IMPLEMENTATION_BLUEPRINT.md#r13), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)

---

## 1. Executive Summary & Component Scope

`GEN-03` implements structured, evidence-grounded document content generation for CVs and explicitly requested Cover Letters. It operates strictly within the frozen inputs, options, and measured context sealed by `GEN-02`, performing local structured inference through `LLM-01` (`LocalModelProvider`).

Every candidate factual claim is bound to an approved, purpose-permitted fact from the admitted context bundle through typed `C08` evidence references. Every job or employer factual claim cites exact excerpts from the frozen posting text. All subjective text, uncertainty, and source limitations remain prominently tagged for human review.

### Core Architecture & Behavioral Invariants

1. **Versioned Content Contract (C14 v2.0)**:
   - Generates structured `DraftDocumentV2` (`schema_version: "2.0"`) with ordered sections (`DraftSection`), ordered entries (`DraftEntry`), atomic claims (`DraftClaim`), subjective blocks (`SubjectiveBlock`), protected source values (`ProtectedSourceValue`), and typed review issues (`DraftReviewIssue`).
   - Legacy C14 `DraftDocument` v1.0 remains readable without manufactured provenance via `read_draft_json()`. Unsupported schema versions raise clear validation errors rather than silently downcasting or discarding fields.
   - Physical artifact contracts (`C14_artifact`) are unchanged and are not created by GEN-03.

2. **Conservative Source-Extractive Recipe**:
   - Initial versioned recipes (`gen03-cv-extractive-v1` for CV, `gen03-letter-extractive-v1` for Cover Letter, framing `gen03-json-v1`) enforce strict source extraction.
   - Candidate factual claims must copy exact strings from admitted facts (`title`, `organization`, `start_date`, `end_date`, `skills`, `metrics`, `claims`). Unsupported skills or metrics, inflated figures, or changed dates fail admission immediately.
   - Factual excerpts preserve original source language; headings and subjective phrases are localized to the requested language (`de` or `en`).
   - **Crucial Invariant**: Code checks and valid evidence IDs **do not prove truthful paraphrasing or semantic entailment**. Every claim carries an explicit `semantic_review_required` issue with `requires_human_review=True`.

3. **Strict Claim Attribution & Untrusted Job Isolation**:
   - Every claim is typed with `claim_subject="candidate"` (referencing candidate fact UUID) or `claim_subject="job"` (referencing posting revision hash and field path).
   - Compound assertions are split; job requirements or employer statements can never be attributed as candidate facts.
   - All job fields, candidate strings, and URLs are treated as untrusted data. Hostile prompt injections (e.g. delimiters, system instruction overrides) remain inert data and cannot alter schema, instructions, or evidence.

4. **Durable Persistence & Idempotent Restart (Migration 012)**:
   - Physical model attempts are tracked in `draft_content_attempts`, immutable audits in `draft_model_audits`, and logical draft commitments in `draft_content_results`.
   - CAS commit: first committed matching logical draft wins; subsequent retries reopen the committed content without repeated model inference.
   - Restart before worker checkpoint reuses committed draft content; a completed checkpoint with missing or corrupt content produces an inspectable integrity error.

5. **Exclusions**:
   - GEN-03 does **not** render DOCX/PDF files or install renderers (GEN-05 ownership).
   - GEN-03 does **not** deliver files or update Salesforce (GEN-06 ownership).
   - GEN-03 does **not** approve drafts or advance requests to `ready_for_review` (human approval and GEN-04 validation gate remain required).

---

## 2. Architecture & Component Interfaces

### Module Overview

| Module | Purpose |
|---|---|
| `src/job_automation/contracts/draft_content.py` | Contracts: `DraftClaim`, `DraftEntry`, `DraftSection`, `SubjectiveBlock`, `ProtectedSourceValue`, `DraftReviewIssue`, `DraftContentProposal`, `DraftDocumentV2`, `read_draft_json`. |
| `src/job_automation/generation/draft_records.py` | Durable contracts: `DraftGenerationReceipt`, `DraftGenerationResult`. |
| `src/job_automation/generation/draft_prompts.py` | Versioned recipes: `DraftRecipe`, `DraftRecipeProvider`, catalog of headings (`HEADINGS`) and approved subjective phrases (`SUBJECTIVE`). |
| `src/job_automation/generation/draft_inputs.py` | `verify_binding`: verifies frozen seal, context receipt, snapshots, options digest, and context budget before model calls. |
| `src/job_automation/generation/draft_grounding.py` | `admit`: validates proposal sections, admits exact factual claims against source fields, validates job spans, attaches review issues. |
| `src/job_automation/generation/draft_service.py` | `DraftContentService`: orchestrates binding verification, input binding, structured LLM-01 inference, identity verification, content admission, and atomic persistence. |
| `src/job_automation/generation/draft_adapter.py` | `DraftGeneratorV2`: adapter implementing the `Generator` protocol for `GenerationCoordinator` (GEN-01). |
| `src/job_automation/storage/repositories/draft_content.py` | `DraftContentRepository`: SQLite repository managing `draft_content_attempts`, `draft_model_audits`, and `draft_content_results`. |
| `src/job_automation/storage/migrations.py` | Migration 012 (`MIGRATION_012_DRAFT_CONTENT`): companion tables for attempts, audits, and results. |
| `tests/manual/draft_smoke.py` | Manual live smoke runner separating offline scripted testing from live model quality review. |

### Storage Schema (Migration 012)

```sql
CREATE TABLE draft_content_attempts (
    attempt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    logical_key TEXT NOT NULL,
    binding_hash TEXT NOT NULL,
    seal_id TEXT NOT NULL REFERENCES generation_frozen_seals(seal_id) ON DELETE RESTRICT,
    context_receipt_id TEXT NOT NULL REFERENCES generation_context_receipts(receipt_id) ON DELETE RESTRICT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    call_json TEXT,
    call_id TEXT NOT NULL UNIQUE,
    receipt_json TEXT,
    receipt_hash TEXT
);

CREATE TABLE draft_model_audits (
    call_id TEXT PRIMARY KEY REFERENCES draft_content_attempts(call_id) ON DELETE RESTRICT,
    audit_json TEXT NOT NULL,
    audit_hash TEXT NOT NULL
);

CREATE TABLE draft_content_results (
    request_id TEXT PRIMARY KEY REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    logical_key TEXT NOT NULL UNIQUE,
    receipt_id TEXT NOT NULL UNIQUE REFERENCES draft_content_attempts(attempt_id) ON DELETE RESTRICT
);
```

---

## 3. Versioned Prompts and Recipes

### Recipe Catalog

| Parameter | CV Recipe | Cover Letter Recipe |
|---|---|---|
| **Prompt Version** | `gen03-cv-extractive-v1` | `gen03-letter-extractive-v1` |
| **Framing Version** | `gen03-json-v1` | `gen03-json-v1` |
| **Proposal Schema ID** | `draft_content_proposal_v1` (v1.0) | `draft_content_proposal_v1` (v1.0) |
| **Supported Languages** | `de` (German), `en` (English) | `de` (German), `en` (English) |
| **Supported Templates** | `content-basic`, `content-compact` | `content-basic`, `content-compact` |
| **Allowed Section Headings** | `summary`, `experience`, `education`, `skills` | `opening`, `experience`, `motivation`, `closing` |
| **Subjective Motivation** | Strictly from catalog; tagged for human review | Strictly from catalog; tagged for human review |

### Recipe Hash & Configuration

`DraftRecipe` captures prompt version, model identifier, model digest, generation settings (`temperature=0.1`, `num_predict=output_reserve`), context ceiling, output reserve, safety allowance, exact measurement policy, document type, target language, template ID, and schema digest. The `recipe_hash` is computed as a SHA-256 digest over the canonical JSON representation of the entire recipe and is sealed into `FrozenContextRecipe` before context measurement.

---

## 4. Verification and Acceptance Matrix

### Automated Offline Test Suite (`tests/generation/content/`)

All 72 tests pass offline without external network or running model servers:

| Test File | Test Count | Scope |
|---|---|---|
| `test_generation.py` | 56 | 8-scenario matrix (CV/Cover Letter × DE/EN × JSON/RAG), valid ID vs false text rejection, hostile/malicious proposal rejection, prompt injection neutrality, malformed JSON handling, model failures/timeouts/length cuts, model identity verification, legacy C14 compatibility, budget overflow handling, protected date precision, ordered entries roundtrip. |
| `test_recovery.py` | 11 | Receipt commit before checkpoint recovery, corrupt receipt/content rejection without repeat inference, interrupted attempt retention, capacity failure handling, zero mutable source reads, frozen body tamper rejection, retention inventory protection, schema export separation. |
| `test_windows_paths.py` | 3 | Windows paths with spaces, German umlauts (`ä, ö, ü, ß`), and deep directory structures. |
| `test_windows_restart.py` | 2 | Native Windows subprocess execution from changed working directory with Unicode spaces; checkpoint repair without duplicate model calls. |

### Repository Regression Gate

- `tests/generation/content/`: 72 / 72 passed
- `tests/generation/inputs/`: 46 / 46 passed
- `tests/generation/`: 120 / 120 passed
- `tests/models/`: 102 / 102 passed
- `tests/contracts/`: 48 / 48 passed
- `tests/storage/`: 60 / 60 passed
- `tests/context/`: 250 / 250 passed
- `tests/operations/`: 78 / 78 passed
- **Complete Workspace**: **1,546 / 1,546 tests passed** (exit code 0)

### Native Windows Hardening

- Tested with PowerShell under native Windows 11.
- Executed under temporary non-ASCII basetemp directories (`$env:TEMP\GEN-03 Prüfung ä ...\Daten Größe`).
- Child subprocess test verified safe SQLite connection closure, atomic backup, and detached verification across working directory changes.

---

## 5. Separation of Fake-Model Checks from Live Quality Review

| Evaluation Tier | Implementation / Tool | Status | Findings |
|---|---|---|---|
| **Offline Structural & Grounding Conformance** | `pytest tests/generation/content` with `ScriptedModelTransport` | **VERIFIED** | Enforces schema validation, citation kinds, prompt isolation, budget bounds, and transaction rollbacks. |
| **Live Model Execution & Smoke Test** | `python tests/manual/draft_smoke.py` | **OPERATIONAL / CLEAN GATE** | Probes local loopback (`http://127.0.0.1:11434`), checks available models, verifies connectivity, and cleanly reports live quality status. |
| **Live Quality Review & Semantic Verification** | Human review & benchmark evaluation (MODEL-02 / EVAL-01) | **PENDING** | Semantic accuracy, fluency, and stylistic appropriateness require human assessment and live model evaluation against defined benchmarks. |

---

## 6. Remaining Quality Limitations & Consumer Handoff to GEN-04

1. **Conservative Source-Extractive Phrasing**:
   - The current implementation intentionally forbids free-form factual paraphrasing and translation of factual claims. Factual claims must reproduce the exact text of the cited fact or posting excerpt.
   - Relaxing this to allow generative paraphrasing requires an evaluated recipe and human review; valid evidence citations alone do not prove truthfulness.

2. **Semantic Entailment Disclaimer**:
   - Matching a valid candidate fact UUID does **not** certify that rewritten text truthfully reflects candidate experience (e.g. rewriting "participated in" to "directed").
   - GEN-03 attaches `semantic_review_required` issues to all claims; downstream `GEN-04` must execute deeper factual consistency checks before any review presentation.

3. **Missing Candidate Identity Facts**:
   - `C01 ProfileSnapshot` does not define dedicated candidate name or contact fields. Missing identity data remains `null` with a `candidate_identity_missing` review issue rather than inventing synthetic names.

4. **Retrieval Misses vs. Candidate Truth**:
   - In RAG context, facts omitted due to retrieval budget constraints do not imply the candidate lacks those skills. GEN-03 preserves `upstream_warnings_present` to ensure human reviewers are aware of omitted context.

