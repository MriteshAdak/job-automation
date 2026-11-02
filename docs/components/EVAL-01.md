# Component Handoff: EVAL-01 — Paired Evaluation Harness, Context Strategy Benchmarks, and Reviewer Audit

Component ID: **EVAL-01**  
Status: **VERIFIED (Offline / Integration / Scripted-Transport / Native Windows) — Live acceptance pending local Ollama benchmark (EG5) and RUN production export integration (EG1/EG4)**  
Phase: **Phase 0 / P0 (S01–S08 Implemented; S09–S10 Explicitly DEFERRED as Phase 1 Extensions)**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), §§4, 5, 7, 8, 9; [docs/stories/EVAL-01.md](../stories/EVAL-01.md)  
Prerequisite Handoffs:
- [DATA-01](DATA-01.md) (**VERIFIED**)
- [INGEST-01](INGEST-01.md) (**VERIFIED**)
- [INGEST-02](INGEST-02.md) (**VERIFIED**)
- [IDENTITY-01](IDENTITY-01.md) (**VERIFIED**)
- [IDENTITY-02](IDENTITY-02.md) (**VERIFIED**)
- [MATCH-01](MATCH-01.md) (**VERIFIED**)
- [MATCH-02](MATCH-02.md) (**VERIFIED**)
- [SYNC-01](SYNC-01.md) (**VERIFIED**)
- [CONTEXT-04](CONTEXT-04.md) (**VERIFIED**)
- [LLM-01](LLM-01.md) (**VERIFIED**)
- [RUN-01](RUN-01.md) (**VERIFIED**)  
Date Completed: 29 October 2026  
Direct Covered Requirements: [R13](../../IMPLEMENTATION_BLUEPRINT.md#r13), [R05](../../IMPLEMENTATION_BLUEPRINT.md#r05), [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06), [R07](../../IMPLEMENTATION_BLUEPRINT.md#r07), [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16), with [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14) constraints  

---

## 1. Executive Summary & Component Scope

`EVAL-01` delivers the controlled, reproducible paired evaluation framework comparing **JSON Context** (baseline) against **RAG Context** (treatment) under identical candidate profile truth, search policies, model parameters, and prompt structures.

It provides reproducible labeled evaluations, intermediate stage capture (retrieval, ranking, context packing, inference, and validation), failure attribution, honest metrics calculation, blinded human reviewer packets, reviewer corrections without mutating candidate truth or search policy, seeded stratified rejected-job sampling, and isolated local persistence.

### Core Architecture & Behavioral Invariants

1. **Strict Publication Firewall & Zero Salesforce Side Effects**:
   - Accidental publication is architecturally impossible.
   - Zero Salesforce client or gateway instantiation.
   - Zero writes to production `canonical_jobs`, `assessments`, or `sync_operations` tables.
   - Physical separation of storage: evaluation artifacts and pairs reside in an isolated SQLite database (`evaluation.db`) with its own migration ledger (`eval_schema_migrations`).
   - Path aliasing rejection: prevents evaluation database from pointing to or aliasing the production database (including Windows case-folding and junction aliases).
   - Strict `enable_sync = False` enforcement: attempting to set `enable_sync=True` raises `PublicationAttemptBlockedError`. There is no `--publish` override flag.

2. **Controlled Paired Execution Engine**:
   - Holds all controls constant across comparison arms: candidate profile snapshot hash, search policy fingerprint, model identifier, model SHA-256 digest, prompt version and template hash, context token limits, and decoding settings. The **only** treatment difference is the context strategy (`JSON` vs `RAG`).
   - Executes deterministic baseline first once per case (Precedence 1).
   - Counterbalanced serial execution order (`[JSON, RAG]` vs `[RAG, JSON]`) determined deterministically via seed to eliminate order-dependent cache or queue bias.
   - Evaluates arm symmetry and captures raw proposals, admitted context bundles, retrieved chunk IDs, validation issues, stage latencies, and token counts.
   - Handles arm failures and context overflow cleanly: one-arm failures leave the pair explicitly incomplete without corrupting other cases.
   - Reusable committed work: resuming interrupted runs skips completed pairs without redundant model calls.

3. **Stage Failure Attribution**:
   - Hierarchically classifies requirement outcomes into distinct non-overlapping stages:
     - `extraction_loss`: requirement omitted by upstream extractor (not a retrieval failure).
     - `no_evidence_expected`: expected absence of evidence for `GAP` or `UNKNOWN` (not a retrieval failure).
     - `retrieval_loss`: gold fact absent from raw vector retrieval hits ($G_r \not\subseteq H_r$, RAG only).
     - `ranking_loss`: retrieved in raw search but dropped during ranking/top-k pruning ($G_r \not\subseteq K_r$).
     - `budget_packing_loss`: survived ranking but omitted from admitted prompt due to context token budget.
     - `inference_use_loss`: admitted in context prompt, but model failed to cite sufficient facts.
     - `semantic_distortion`: model cited facts but drew a contradictory or distorted conclusion.
     - `unsupported_claim`: model claimed match without basis or cited unadmitted/unknown facts.
     - `supported`: sufficient admitted evidence cited with matching status.
   - JSON retrieval metrics are strictly reported as `None` (`N/A`).

4. **Honest Metrics & Zero-Denominator Discipline**:
   - Zero denominators return `None` (`N/A`) with counts; never fabricate `1.0` or `0.0` for empty sets.
   - 3x3 confusion matrix on completed pairs (`ELIGIBLE`, `REVIEW`, `REJECTED`).
   - Retention false negative rate: $FN / (\text{Gold Eligible} + \text{Gold Review})$.
   - Proposed targets from `settings.py` are explicitly marked `PROPOSED` and separated from empirical observations.
   - Sample limitations explicitly disclaim generalization to the broader German job market.

5. **Blinded Human Review & Truth Immutability**:
   - Review packets blind the context strategy (`Arm A` vs `Arm B` with randomized assignment).
   - Captures active reviewer effort duration in seconds.
   - Immutability guarantee: reviewer corrections **cannot** mutate candidate profile truth or search policy. New fact proposals require `PROFILE-01` snapshot approval; preference adjustments require `POLICY-01`. Any direct modification attempt raises `InputTamperingError`.
   - Idempotent correction import: conflicting unadjudicated edits raise `UnadjudicatedReviewError`.

6. **Stratified Rejected-Job Sampling & Audit**:
   - Read-only population extraction of production system rejects. Excludes comparison records, candidate application status 'Rejected', availability closures, and pending inferences.
   - Stratifies by rejection reason: hard factual failure, exclusion, missing-policy fail, semantic required gap, and low score.
   - Seeded sampling without replacement; row-order invariant frame hash.
   - Strict metric nomenclature: **False-Omission Proportion among Rejects**, strictly not labeled population FNR.

7. **Deferred Phase 1 Document Extensions**:
   - S09 (Document Grounding & Claim Review) and S10 (Rendered Draft & Version Quality) are explicitly **DEFERRED** as Phase 1 extensions because prerequisite generation dependencies (`GEN-02` through `GEN-06`) do not yet exist.
   - Gated by `UnavailablePhase1ExtensionError`.

---

## 2. Delivered Modules & File Mapping

| Path | Purpose | Story |
|---|---|---|
| `src/job_automation/evaluation/settings.py` | Configuration, schema versions (`1.0`), metric spec (`v1.0`), proposed targets, and firewall validation | S01 |
| `src/job_automation/evaluation/errors.py` | Explicit evaluation exception hierarchy (aliasing, tampering, firewall, unadjudicated) | S01 |
| `src/job_automation/evaluation/fingerprints.py` | Canonical JSON serialization and deterministic SHA-256 hashing | S01 |
| `src/job_automation/evaluation/records.py` | Immutable Pydantic models for cases, gold labels, manifests, pairs, arm attempts, reports | S01 |
| `src/job_automation/evaluation/ports.py` | Architectural boundary protocols, case sanitizer, and `assert_no_publication_authority` | S01 |
| `src/job_automation/evaluation/labels.py` | Gold label integrity validation and multi-fact sufficient evidence set alignment | S02 |
| `src/job_automation/evaluation/split.py` | Group-based dataset partitioning and cross-split leakage prevention | S02 |
| `src/job_automation/evaluation/corpus.py` | Labeled 8-case synthetic corpus (English, German, hard fails, C++/C#, prompt injection) | S02 |
| `src/job_automation/evaluation/workspace.py` | Directory structure management, path normalization, and database aliasing guard | S03 |
| `src/job_automation/evaluation/migrations.py` | Independent SQLite schema migrations for evaluation (`eval_schema_migrations`) | S03 |
| `src/job_automation/evaluation/repository.py` | Isolated persistence repository for evaluation cases, pairs, attempts, and reports | S03 |
| `src/job_automation/evaluation/composition.py` | Dependency injection factory with publication firewall assertions | S03 |
| `src/job_automation/evaluation/recovery.py` | Diagnostic resumption planner for interrupted evaluation experiments | S03 |
| `src/job_automation/evaluation/timing.py` | Monotonic stage timer using `time.perf_counter()` | S04 |
| `src/job_automation/evaluation/manifest_validation.py` | Arm symmetry verification and input control extraction | S04 |
| `src/job_automation/evaluation/capture.py` | Intermediate stage trace extraction (retrieval, admitted bundle, validation issues) | S04 |
| `src/job_automation/evaluation/assessment_adapter.py` | Adapter executing deterministic baseline and comparison LLM requests | S04 |
| `src/job_automation/evaluation/runner.py` | Paired execution engine with counterbalanced order and failure isolation | S04 |
| `src/job_automation/evaluation/attribution.py` | Requirement outcome failure classification (extraction, retrieval, packing, inference, semantic) | S05 |
| `src/job_automation/evaluation/metrics.py` | Metric calculations: coverage, citation use, 3x3 confusion matrix, deltas, zero denominators | S05 |
| `src/job_automation/evaluation/reporting.py` | Markdown and text report generators with explicit limitation disclosures | S05 |
| `src/job_automation/evaluation/review.py` | Blinded reviewer packet data structures and randomized Arm A/B generator | S06 |
| `src/job_automation/evaluation/review_export.py` | Export blinded review packets and response templates to JSON | S06 |
| `src/job_automation/evaluation/review_import.py` | Import reviewer corrections with profile and policy immutability validation | S06 |
| `src/job_automation/evaluation/population_reader.py` | Read-only extraction of candidate system rejects and frame hash computation | S07 |
| `src/job_automation/evaluation/sampling.py` | Seeded stratified sampling without replacement across rejection categories | S07 |
| `src/job_automation/evaluation/sample_review.py` | Audit metrics for false-omission proportion among rejects | S07 |
| `src/job_automation/evaluation/cli.py` | CLI subcommands: `check`, `run`, `resume`, `report`, `sample-rejects`, `review-export`, `review-import` | S08 |
| `src/job_automation/cli.py` | Integration of `evaluation` command group into main application CLI | S08 |
| `config/evaluation.example.json` | Non-secret example configuration with placeholders and explicit roots | S08 |

---

## 3. Dependency Gate Verification Status

| Gate ID | Name | Owner | Status | Evidence / Verification |
|---|---|---|---|---|
| **EG1** | Exact frozen inputs | RUN/DATA/IDENTITY | **SATISFIED_OFFLINE** | Frozen case definitions, candidate profile snapshot hashes, search policy fingerprints, and posting revisions verified offline in synthetic corpus. |
| **EG2** | Comparable model execution | MATCH/CONTEXT/LLM | **SATISFIED_OFFLINE** | Shared `AssessorV2` interface, identical deterministic baseline (`MATCH-01`), shared context selector, and strict arm control symmetry verified. |
| **EG3** | Observable evidence capture | MATCH/CONTEXT/LLM | **SATISFIED_OFFLINE** | `extract_arm_trace_data` captures raw retrieved chunks, admitted bundle, model proposal, final assessment, validation issues, and stage latencies. |
| **EG4** | RUN integration and publication isolation | RUN/SYNC | **SATISFIED_OFFLINE** | Isolated SQLite database, zero Salesforce gateway instantiation, production sentinel database completely untouched across runs. |
| **EG5** | Live model service execution | MODEL-01/02 | **PENDING_LIVE** | Offline scripted and deterministic test transports pass; live local Ollama model benchmark pending endpoint availability. |

---

## 4. CLI Commands Reference

All evaluation subcommands are accessible via `python -m job_automation evaluation <action>`:

```powershell
# 1. Check environment, dependency gates, and publication firewall
python -m job_automation evaluation check --eval-root C:\ProgramData\job_automation\evaluation

# 2. Run paired evaluation experiment on labeled corpus
python -m job_automation evaluation run --eval-root C:\ProgramData\job_automation\evaluation --split development --repetitions 1

# 3. Resume interrupted experiment without rerunning completed pairs
python -m job_automation evaluation resume --eval-root C:\ProgramData\job_automation\evaluation --experiment-id <UUID>

# 4. Recreate report from stored experiment records without new inference
python -m job_automation evaluation report --eval-root C:\ProgramData\job_automation\evaluation --experiment-id <UUID> --output report.md

# 5. Perform stratified sampling on rejected job assessments
python -m job_automation evaluation sample-rejects --sample-size 50 --seed 42 --output sample_manifest.json

# 6. Export blinded review packets for human annotation
python -m job_automation evaluation review-export --eval-root C:\ProgramData\job_automation\evaluation --experiment-id <UUID> --output review_packets.json

# 7. Import human review corrections
python -m job_automation evaluation review-import --eval-root C:\ProgramData\job_automation\evaluation --corrections corrections.json
```

---

## 5. Empirical Verification & Test Matrix

All tests execute cleanly under Python 3.12.10 on native Windows.

### Test Breakdown

| Test Suite | Stories | Test Count | Status | Notes |
|---|---|---|---|---|
| `tests/evaluation/test_contracts.py` | S01 | 7 | **PASS** | Frozen models, hashing, firewall validation, loopback checks |
| `tests/evaluation/test_corpus.py` | S02 | 2 | **PASS** | 8 canonical synthetic cases, profile truth, source span verification |
| `tests/evaluation/test_labels.py` | S02 | 5 | **PASS** | Sufficient evidence sets, partial support, contradiction detection |
| `tests/evaluation/test_split.py` | S02 | 3 | **PASS** | Opportunity group partitioning, no split leakage |
| `tests/evaluation/test_isolation.py` | S03 | 3 | **PASS** | SQLite migrations, WAL mode, path aliasing prevention |
| `tests/evaluation/test_no_publication.py` | S03 | 3 | **PASS** | Sentinel production DB, sync operation guard, zero Salesforce writes |
| `tests/evaluation/test_recovery.py` | S03 | 1 | **PASS** | Diagnostic plan, reuse of committed pairs |
| `tests/evaluation/test_paths.py` | S03 | 1 | **PASS** | Absolute path enforcement, normalization |
| `tests/evaluation/test_input_controls.py` | S04 | 2 | **PASS** | Arm control symmetry, prompt growth / drift rejection |
| `tests/evaluation/test_capture.py` | S04 | 1 | **PASS** | Intermediate trace data extraction |
| `tests/evaluation/test_pairs.py` | S04 | 1 | **PASS** | Counterbalanced execution, deterministic baseline precedence |
| `tests/evaluation/test_pair_failures.py` | S04 | 1 | **PASS** | Incomplete pair handling on context overflow |
| `tests/evaluation/test_attribution.py` | S05 | 8 | **PASS** | Hand-calculated failure attribution for all stages |
| `tests/evaluation/test_metrics.py` | S05 | 5 | **PASS** | Zero-denominator safe division, 3x3 confusion matrix, deltas |
| `tests/evaluation/test_reporting.py` | S05 | 1 | **PASS** | Markdown and ASCII text report generation, limitation disclosures |
| `tests/evaluation/test_review.py` | S06 | 2 | **PASS** | Blinded packet generation, review export JSON structure |
| `tests/evaluation/test_corrections.py` | S06 | 3 | **PASS** | Idempotent import, conflict detection, unknown citation rejection |
| `tests/evaluation/test_review_privacy.py` | S06 | 2 | **PASS** | Candidate truth and policy immutability guards |
| `tests/evaluation/test_population_binding.py` | S07 | 2 | **PASS** | Filtering comparison, user-status, and availability records |
| `tests/evaluation/test_sampling.py` | S07 | 3 | **PASS** | Seed reproducibility, row-order invariance, census on small strata |
| `tests/evaluation/test_sample_metrics.py` | S07 | 1 | **PASS** | False omission proportion among rejects, unreviewed tracking |
| `tests/test_cli_evaluation.py` | S08 | 3 | **PASS** | CLI argument parsing, check dispatch, sampling dispatch |
| `tests/evaluation/test_windows_paths.py` | S08 | 2 | **PASS** | Native Windows spaces, German umlauts (`äöü`), casing |
| `tests/evaluation/test_windows_restart.py` | S08 | 2 | **PASS** | Native subprocess execution, handle release, resume flow |
| `tests/evaluation/test_integration.py` | S08 | 1 | **PASS** | Full end-to-end lifecycle on 8 synthetic cases with zero publication |
| **Total Evaluation Tests** | | **65** | **PASS** | 100% passing in 2.26s |
| **Full Repository Test Suite** | | **1311** | **PASS** | Zero regressions across entire project in 58.74s |

---

## 6. Native Windows Recipe Execution

The native PowerShell verification recipe from `docs/stories/EVAL-01.md`:

```powershell
$evalRepo = (Resolve-Path '.').Path
$evalPython = Join-Path $evalRepo '.venv\Scripts\python.exe'
$evalTests = Join-Path $evalRepo 'tests\evaluation'
$evalTemp = Join-Path $env:TEMP ('Job Evaluation Prüfung ä ' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $evalTemp | Out-Null
& $evalPython -m pytest $evalTests (Join-Path $evalRepo 'tests\test_cli_evaluation.py')
if ($LASTEXITCODE -ne 0) { throw 'EVAL component checks failed' }
Push-Location -LiteralPath $evalTemp
try {
    & $evalPython -m pytest (Join-Path $evalTests 'test_windows_paths.py') (Join-Path $evalTests 'test_windows_restart.py') --basetemp (Join-Path $evalTemp 'Test Daten ö')
    if ($LASTEXITCODE -ne 0) { throw 'EVAL native Windows checks failed' }
} finally {
    Pop-Location
}
```

Result: **Executed with exit code 0** (65 evaluation tests passed; native Windows path and restart tests passed in temporary directory with spaces and German umlauts).

---

## 7. Deferred Phase 1 Extensions (S09 & S10)

- **EVAL-01-S09 (Document Grounding & Claim Review)**:
  - Status: **DEFERRED (Phase 1)**
  - Requires implemented `GEN-02` (Input Freezing & Context Assembly), `GEN-03` (Draft Content Generation), and `GEN-04` (Document Claim Validation).
  - Calling code raises `UnavailablePhase1ExtensionError`.
- **EVAL-01-S10 (Rendered Draft & Version Quality)**:
  - Status: **DEFERRED (Phase 1)**
  - Requires implemented `GEN-05` (Document Rendering & Local Version Checkpoints).
  - Calling code raises `UnavailablePhase1ExtensionError`.

---

## 8. Summary of Downstream Recommendations

1. **For CONTEXT-04 / MATCH-02**:
   - Trace data extraction (`extract_arm_trace_data`) successfully isolates raw retrieved fact IDs, ranked fact IDs, and admitted context facts.
   - Preserving distinct raw retrieval vs context budget omissions enables clear separation between vector index recall and token budget packing limits.
2. **For MODEL-02 (Live Benchmarking)**:
   - When running against live local Ollama endpoints (`qwen2.5:7b-instruct`), run paired comparisons with `repetitions_per_pair >= 3` to capture stochastic variance.
   - Use `python -m job_automation evaluation check` to verify loopback host restrictions before live benchmarking.
3. **For RUN-01 (Production Integration)**:
   - Evaluated cases and rejected-job sampling read-only binds seamlessly into production exports without risk of primary assessment overwrites or Salesforce publication.

