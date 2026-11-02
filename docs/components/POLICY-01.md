# Component Handoff: POLICY-01 — Search Policy and Vocabulary

Component ID: **POLICY-01**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Prerequisite Handoffs: [docs/components/FND-01.md](FND-01.md)  
Planning Reference: [docs/stories/POLICY-01.md](../stories/POLICY-01.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R01](../../IMPLEMENTATION_BLUEPRINT.md#r01), [R05](../../IMPLEMENTATION_BLUEPRINT.md#r05) (supporting R14, R15, R16)  

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing POLICY-01, all prerequisite contracts and services from **FND-01** were inspected and verified:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C02 SearchPolicy Contract** | FND-01 | **VERIFIED** | `job_automation.contracts.policy` (`SearchPolicy`, `HardCriterion`, `PreferenceRule`, `RelevanceConfig`). |
| **Error Taxonomy & Issues** | FND-01 | **VERIFIED** | `job_automation.contracts.errors` (`ValidationIssue`, `ClassifiedError`, `ErrorCategory`). |
| **Configuration & Paths** | FND-01 | **VERIFIED** | `job_automation.configuration` (`AppConfig`, `ResolvedPaths`, `load_config`). |
| **C06 NormalizedPosting** | FND-01 | **VERIFIED** | Target catalog aligns with C06 posting fields (`title`, `workplace_type`, `locations`, `compensation`, etc.). |
| **RuleEvaluator Protocol** | FND-01 | **VERIFIED** | `job_automation.contracts.interfaces.RuleEvaluator` protocol exists. |

### Missing Prerequisite Report
- **Upstream interfaces**: Zero missing prerequisite interfaces. All required foundational models and configuration boundaries are present.
- **Downstream interfaces**: Concrete implementation of the `RuleEvaluator` protocol (MATCH-01) is absent as expected. In accordance with blueprint §6 and component boundaries, POLICY-01 implements policy validation, vocabulary normalization, conflict detection, and deterministic fingerprinting only; it does not evaluate job postings or infer candidate eligibility.

---

## 2. Implementation Summary by Story

All eight planned stories from `docs/stories/POLICY-01.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **POLICY-01-S01** | Semantic specification & public boundary | **VERIFIED** | `models.py`, `fields.py`, `__init__.py`. Finite target catalog, allowed operators, structured `SalaryOperand`, and strict rejection of forbidden candidate targets (`candidate.*`). |
| **POLICY-01-S02** | Safe local C02 loader & structural diagnostics | **VERIFIED** | `loader.py`. Enforces UTF-8 (handling BOM), duplicate key detection, non-dict root rejection, non-finite number rejection, explicit `on_missing` tracking, and safe allowlisted error messages. |
| **POLICY-01-S03** | German/English vocabulary normalization & alias validation | **VERIFIED** | `vocabulary.py`. Unicode NFC normalization, whitespace collapsing, casefold lookup, punctuation preservation (`C++`, `C#`, `.NET`), empty alias rejection, duplicate canonical collision detection, ambiguous alias detection, alias chain rejection, and namespace isolation. |
| **POLICY-01-S04** | Hard/preferred validation & effective missing resolution | **VERIFIED** | `criteria.py`, `missing.py`. Unique rule IDs, enum validation, finite weight validation, D03 missing precedence (`explicit_rule` > `field_default` > `global_default unknown`), and bare numeric salary rejection. |
| **POLICY-01-S05** | Bounded cross-policy conflict detection | **VERIFIED** | `conflicts.py`. Disjoint scalar domain conflicts, inverted salary bounds, required term vs exclusion conflicts (including alias resolution), soft preference unreachable warnings, and keyword contradictions. |
| **POLICY-01-S06** | Deterministic fingerprint & effective version binding | **VERIFIED** | `fingerprint.py`. Tagged SHA-256 (`policy-v1:sha256:<hex64>`) over canonical UTF-8 JSON bytes with sorted keys and effective settings. Invariant to whitespace, CRLF, and authored labels; sensitive to all meaningful policy changes. |
| **POLICY-01-S07** | Read-only CLI & synthetic policy examples | **VERIFIED** | `cli.py`, `config/policy.example.json`, `config/policy.office.example.json`. Added `policy check` with `--policy`, `--config`, and `--json`. Exit code 0 for valid (including warnings), exit code 2 for errors. |
| **POLICY-01-S08** | Integrated checks, native Windows evidence & handoff | **VERIFIED** | `test_integration.py`, `test_schema_compatibility.py`, 13 synthetic fixtures with `README.md`, native Windows verification recipe execution, and component handoff. |

---

## 3. Files Created and Modified

### Source Files (`src/job_automation/policy/`)
- [`src/job_automation/policy/__init__.py`](../../src/job_automation/policy/__init__.py): Public exports for policy models, vocabulary, target catalog, and validation service.
- [`src/job_automation/policy/models.py`](../../src/job_automation/policy/models.py): Domain models (`SalaryOperand`, `EffectiveMissingAction`, `PolicyMetadata`, `EffectivePolicy`, `PolicyValidationResult`).
- [`src/job_automation/policy/fields.py`](../../src/job_automation/policy/fields.py): Finite C06 target catalog, operator specifications, and candidate/skills field detectors.
- [`src/job_automation/policy/vocabulary.py`](../../src/job_automation/policy/vocabulary.py): Unicode normalization, German/English vocabulary validation, and two-namespace lookup (`role_aliases` and `skill_aliases`).
- [`src/job_automation/policy/loader.py`](../../src/job_automation/policy/loader.py): Safe local JSON loader with BOM support, duplicate key rejection, and explicit `on_missing` preservation.
- [`src/job_automation/policy/criteria.py`](../../src/job_automation/policy/criteria.py): Semantic validation for hard criteria, preferences, exclusions, relevance config, and context strategy.
- [`src/job_automation/policy/missing.py`](../../src/job_automation/policy/missing.py): D03 missing-information precedence engine.
- [`src/job_automation/policy/conflicts.py`](../../src/job_automation/policy/conflicts.py): Cross-policy contradiction and unreachable-preference detection.
- [`src/job_automation/policy/fingerprint.py`](../../src/job_automation/policy/fingerprint.py): Canonical payload serializer and tagged SHA-256 fingerprint generator.
- [`src/job_automation/policy/validation.py`](../../src/job_automation/policy/validation.py): Comprehensive validation pipeline coordinator.
- [`src/job_automation/policy/service.py`](../../src/job_automation/policy/service.py): High-level `PolicyService` facade.
- [`src/job_automation/policy/cli.py`](../../src/job_automation/policy/cli.py): CLI subcommand handlers for `policy check`.

### CLI & Configuration Updates
- [`src/job_automation/cli.py`](../../src/job_automation/cli.py): Registered `policy` subcommand group.
- [`config/policy.example.json`](../../config/policy.example.json): Corrected synthetic technical search policy separating geography from workplace type and using supported fields.
- [`config/policy.office.example.json`](../../config/policy.office.example.json): Synthetic office/project management search policy with German/English aliases and RAG context strategy.
- [`README.md`](../../README.md): Documented `job_automation policy check` command usage.

### Fixtures and Tests (`tests/`)
- [`tests/fixtures/policy/README.md`](../../tests/fixtures/policy/README.md): Catalog of synthetic fixtures.
- 13 synthetic policy fixtures in `tests/fixtures/policy/`:
  - `valid_tech.json`, `valid_office.json`, `invalid_duplicate_key.json`, `invalid_duplicate_rule_id.json`, `invalid_ambiguous_alias.json`, `invalid_alias_chain.json`, `invalid_candidate_field.json`, `invalid_unsupported_target.json`, `invalid_unsupported_schema.json`, `invalid_bare_salary.json`, `invalid_contradictory_hard.json`, `invalid_exclusion_conflict.json`, `warning_unreachable_preference.json`.
- 10 test modules under [`tests/policy/`](../../tests/policy/):
  - `test_contract_boundary.py`, `test_loader.py`, `test_vocabulary.py`, `test_criteria.py`, `test_missing.py`, `test_conflicts.py`, `test_fingerprint.py`, `test_cli.py`, `test_integration.py`, `test_schema_compatibility.py`.

---

## 4. Key Architectural Decisions (D01–D09)

1. **D01: Supported C02 Target Catalog & Service Result**: Established a finite catalog of supported C06 fields (`title`, `description_clean`, `company_name_hint`, `workplace_type`, `employment_type`, `advert_language`, `locations.*`, `remote_eligibility_restrictions`, `compensation.*`). Arbitrary traversal, code expressions, and candidate facts are forbidden. Returns a structured `PolicyValidationResult` containing `EffectivePolicy` with immutable C02 models.
2. **D02: Search Scope vs. Candidate Eligibility Separation**: `regions` defines search discovery scope (`["DE"]`); hard geographic requirements must be explicit in `hard_criteria` on `locations.country`. Desired salary bounds belong to C02; candidate salary history belongs to C01. Omitted candidate facts are never inferred.
3. **D03: Missing-Information Precedence & Non-Factual Semantics**: Resolved precedence:
   - Explicit rule-level `on_missing` in input JSON -> `explicit_rule`
   - Field default in `missing_information_behavior` -> `field_default`
   - Global default -> `global_default unknown`  
   An explicit `pass` or `fail` disposition is an operational policy action, never factual evidence about a job or candidate.
4. **D04: Exclusions & Conflict Detection**: Exclusions are literal strings; regular expression patterns are forbidden (`regex_exclusion_forbidden`). Bounded conflict checks detect disjoint scalar domains, inverted salary bounds, required/excluded term collisions (including alias resolution), and flag unreachable preferences as warnings without altering hard constraints.
5. **D05: German/English Vocabulary Normalization & Alias Namespaces**: Unicode NFC normalization, whitespace trimming/collapsing, and `str.casefold()` matching for case-insensitive lookup. Distinctive punctuation (`C++`, `C#`, `.NET`) is preserved. `role_aliases` and `skill_aliases` maintain independent namespaces. Blank terms, canonical collisions, ambiguous aliases, and alias chains are rejected with clear diagnostics.
6. **D06: Tagged SHA-256 Fingerprint & Effective Version Binding**: Fingerprint format: `policy-v1:sha256:<64 hex chars>` computed over canonical UTF-8 JSON bytes (sorted keys, normalized collections, materialized missing actions, version bindings). Authored labels are retained as metadata while `effective_policy.policy.policy_version` is bound to the computed fingerprint.
7. **D07: Relevance Scales & Operand Constraints**: Supported score scale is fixed to `"0-100"`. Optional `min_score_threshold` is bounded to `[0.0, 100.0]`. Preference weights are finite floats in `[0.0, 1.0]`. Compensation operands require explicit positive amount, 3-letter currency code, and salary period; bare numbers are rejected.
8. **D08: Native Windows CLI**: Provided `python -m job_automation policy check` with `--policy <path>` or `--config <app.json>`. Exit code 0 for valid policies (with warnings visible); exit code 2 for validation or missing-file errors. Operates cleanly with German umlauts and space-containing paths without creating runtime directories.
9. **D09: Pending User Preferences**: Real user preferences remain pending; synthetic examples are explicitly labeled.

---

## 5. Verification Commands and Actual Results

### Automated Test Suite Execution
Command executed:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
testpaths: tests
plugins: cov-6.3.0
collected 212 items

tests\contracts\test_context_model_assessment.py ......                  [  2%]
tests\contracts\test_contract_catalog.py ............................... [ 17%]
.                                                                        [ 17%]
tests\contracts\test_errors.py ...                                       [ 19%]
tests\contracts\test_interfaces.py .....                                 [ 21%]
tests\contracts\test_primitives.py .......                               [ 25%]
tests\contracts\test_profile_policy_evidence.py ....                     [ 26%]
tests\contracts\test_source_posting_identity.py ......                   [ 29%]
tests\contracts\test_work_records.py ....                                [ 31%]
tests\policy\test_cli.py .........                                       [ 35%]
tests\policy\test_conflicts.py ......                                    [ 38%]
tests\policy\test_contract_boundary.py .....                             [ 41%]
tests\policy\test_criteria.py ........                                   [ 44%]
tests\policy\test_fingerprint.py .....                                   [ 47%]
tests\policy\test_integration.py ..                                      [ 48%]
tests\policy\test_loader.py ........                                     [ 51%]
tests\policy\test_missing.py ..                                          [ 52%]
tests\policy\test_schema_compatibility.py ...                            [ 54%]
tests\policy\test_vocabulary.py ............                             [ 59%]
tests\profile\test_evidence_store.py ....                                [ 61%]
tests\profile\test_history.py .                                          [ 62%]
tests\profile\test_inclusion.py ....                                     [ 64%]
tests\profile\test_intake.py .....                                       [ 66%]
tests\profile\test_lifecycle.py .                                        [ 66%]
tests\profile\test_provenance.py ..                                      [ 67%]
tests\profile\test_publication.py .....                                  [ 70%]
tests\profile\test_references.py ..                                      [ 71%]
tests\profile\test_repository.py .....                                   [ 73%]
tests\profile\test_validation.py .........                               [ 77%]
tests\storage\test_connection.py ...                                     [ 79%]
tests\storage\test_duplicate_keys.py ......                              [ 82%]
tests\storage\test_filestore.py ....                                     [ 83%]
tests\storage\test_migrations.py ....                                    [ 85%]
tests\storage\test_recovery.py ....                                      [ 87%]
tests\storage\test_repositories.py .......                               [ 91%]
tests\storage\test_transactions.py ....                                  [ 92%]
tests\test_cli.py .....                                                  [ 95%]
tests\test_cli_profile.py ..                                             [ 96%]
tests\test_cli_storage.py ..                                             [ 97%]
tests\test_configuration.py ......                                       [100%]

============================= 212 passed in 6.23s =============================
```

### Test Coverage Execution
Command executed:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\policy --cov=job_automation.policy --cov-report=term-missing
```
Output:
```text
Name                                       Stmts   Miss  Cover
--------------------------------------------------------------
src\job_automation\policy\__init__.py         12      0   100%
src\job_automation\policy\cli.py              63     13    79%
src\job_automation\policy\conflicts.py       112     11    90%
src\job_automation\policy\criteria.py        135     38    72%
src\job_automation\policy\fields.py           21      0   100%
src\job_automation\policy\fingerprint.py      52      7    87%
src\job_automation\policy\loader.py           66     10    85%
src\job_automation\policy\missing.py          23      1    96%
src\job_automation\policy\models.py           44      0   100%
src\job_automation\policy\service.py          28      3    89%
src\job_automation\policy\validation.py       59      9    85%
src\job_automation\policy\vocabulary.py      108     12    89%
--------------------------------------------------------------
TOTAL                                        723    104    86%
```

### Native Windows Verification Recipe Results
Executed from native PowerShell on Windows:

| Verification Scenario | Target / Command | Result | Exit Code | Notes |
|---|---|---|---|---|
| **Interpreter Check** | `.\.venv\Scripts\python.exe --version` | `Python 3.12.10` | 0 | Clean execution |
| **Component & Contract Suite** | `pytest .\tests\policy .\tests\contracts ...` | `138 passed` | 0 | All contract and policy tests pass |
| **Complete Regression** | `pytest` | `212 passed` | 0 | Zero regressions across repo |
| **Technical Example Policy** | `policy check --policy config\policy.example.json --json` | `VALID`, fingerprint `dc47125e...` | 0 | Valid JSON output |
| **Office Example Policy** | `policy check --policy config\policy.office.example.json --json` | `VALID`, fingerprint `7a0ce80a...` | 0 | Valid JSON output |
| **Unicode & Space Path** | `Policy Prüfung <uuid>\Suchregel ä.json` via `--config` | `VALID`, fingerprint `dc47125e...` | 0 | Preserved through German paths |
| **Different Working Directory** | Executed from `$env:TEMP` | `VALID`, identical fingerprint | 0 | Config-relative anchoring confirmed |
| **No Runtime Side Effects** | Checked external data root existence | `Test-Path` returned `False` | 0 | No directories created by check |
| **Missing Policy File** | `policy check --policy missing.json --json` | `FAILED`, code `missing_policy_file` | 2 | Safe diagnostic, fingerprint null |
| **Malformed JSON** | `policy check --policy malformed.json --json` | `FAILED`, code `malformed_json` | 2 | Safe diagnostic, no traceback |

### Live Service Applicability
- **External Network / APIs**: Not applicable (POLICY-01 is completely offline).
- **Salesforce Org**: Not applicable (no mutations belong in POLICY-01).
- **Ollama / Local LLM**: Not applicable (no inference belongs in POLICY-01).

---

## 6. Invariants and Separation from Candidate Facts

- **C01 Candidate Independence**: Loading, validating, or fingerprinting a search policy requires zero candidate or profile data. It never creates, infers, or mutates candidate proficiency, work authorization, salary history, or target location eligibility.
- **Hard vs. Preferred Distinction**: Hard criteria are explicit constraints; soft preferences remain separate ranking signals with weights and cannot silently become disqualifying gates.
- **Deterministic Immutability**: The computed fingerprint uniquely identifies the effective policy configuration. Returning an effective C02 model ensures downstream consumers receive an immutable, fingerprinted policy contract.

---

## 7. Guidance for Dependent Components

- **MATCH-01 (Deterministic Matching & Assessment)**:
  - Consume `EffectivePolicy.policy` (C02 `SearchPolicy`) and inspect `policy.policy_version` to obtain the effective fingerprint.
  - Implement the `RuleEvaluator` protocol: `evaluate_rules(revision, policy, eligibility) -> Assessment`.
  - Propagate `policy.policy_version` directly into C11 `Assessment.policy_version`.
  - Use `NormalizedVocabulary` or alias groups for title/skill term expansion.
  - Evaluate hard criteria with effective materialized `on_missing` actions.
- **RUN-01 & DATA-01 (Orchestration & Storage)**:
  - Retain `EffectivePolicy.canonical_bytes` and `EffectivePolicy.metadata.effective_version`.
  - Trigger job reassessment whenever `effective_version` changes, even if authored version strings match.

