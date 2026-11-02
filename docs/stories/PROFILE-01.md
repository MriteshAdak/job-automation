# PROFILE-01 — Candidate evidence management

Status: **PLANNED** · Planning date: 27 October 2026 · Component: **PROFILE-01 only** · Phase 0

Baseline: [IMPLEMENTATION_BLUEPRINT.md][blueprint], v1.0, 26 October 2026. Requirement IDs refer to §2; contracts to §4; correctness rules to §5; component ownership to §6; implementation and handoff instructions to §8; native Windows conventions to §9. These stories describe future implementation. No application code, candidate data, schema, or migration is created by this planning task.

## Repository evidence and scope

Read [README.md](../../README.md), the blueprint, the [FND-01 handoff][fnd], the [DATA-01 handoff][data], the existing [FND-01 stories](FND-01.md), and the relevant contracts, schemas, fixtures, configuration, CLI, storage implementation, and tests. No applicable `AGENTS.md` was found in the repository or checked ancestor directories. README and blueprint §§8–9 supply the repository working instructions. `docs/stories/DATA-01.md` is absent, as its handoff records; do not invent a prerequisite story document.

| Evidence inspected | Actual baseline and planning consequence |
|---|---|
| FND-01 handoff | Reports VERIFIED, schema 1.0, Python 3.12.10, and 78 passing tests on native Windows. These are prior recorded results, not fresh PROFILE-01 verification. |
| DATA-01 handoff | Reports VERIFIED, database migrations 1/2, 112 passing tests, and native Windows storage checks. Its suggestion to store profiles through storage is guidance; no profile persistence API exists yet. |
| `src/job_automation/contracts/profile.py`, `base.py`, `primitives.py` | C01 and fact/approval/eligibility models exist. Frozen Pydantic models contain mutable lists/dicts. Eligibility and permission defaults, null end-date wording, and approval validation require explicit decisions below. |
| `contracts/evidence.py`, `context.py`, `interfaces.py`, `generation.py` | Candidate C08 has `profile_version` and `fact_id`, with no candidate ID. C09 and C13 carry profile versions. `ContextSelector` accepts a snapshot but has no intended-use parameter. There is no profile service protocol. |
| `schemas/v1/C01_profile_snapshot.schema.json`, C08 schema, contract fixtures/tests | Existing structural examples are synthetic. They do not establish human approval, durable immutability, parent integrity, permission enforcement, or historical resolution. The catalog checks typed fixtures and schema-file parsing; it does not establish full JSON Schema validation parity. |
| `storage/engine.py`, `connection.py`, `migrations.py`, repositories and `filestore.py` | SQLite connection, transactions, checksummed migrations, and job/work repositories exist. There are no profile tables/repositories. Filestore writes raw/artifact files with overwrite behavior; it is not an immutable profile evidence store. |
| `configuration.py`, `cli.py`, `pyproject.toml`, `.gitignore` | `ResolvedPaths.profiles_dir` exists beneath the external data root. No active-profile setting or profile commands exist. CLI exposes configuration and storage commands. Dependency constraints are ranges despite handoff wording about pins; reuse the environment and record actual versions rather than claiming a lockfile exists. |

Direct requirements are **R06, R11, R15**: approved evidence shared by JSON/RAG, traceable candidate claims, and protection of candidate data. **R09, R14, R16** support persistence, Windows operation, and audit/recovery; **R01** supplies the boundary between candidate truth and search preferences. PROFILE-01 prepares the inputs for these requirements; it does not complete context construction, matching, document generation, or the whole Phase 0 gate.

In scope: local manual fact intake/review; stable identities; provenance; explicit approval; versioned inclusion rules; immutable C01 publication; history and exact C08 resolution; necessary SQLite migration and CLI wiring; synthetic tests and handoff.

Downstream ownership remains with POLICY-01 (search criteria), MATCH-01 (eligibility evaluation), CONTEXT-01–04 (JSON serialization, chunks, indexing, retrieval and token budgets), GEN-02/04 (frozen generation inputs and document validation), OPS-01 (cleanup/backups), and RUN-01 (pipeline/worker orchestration). No LLM importer, model call, document parser/OCR, Salesforce integration, scheduler, automatic drafting, or application submission is required here. Future LLM-assisted proposals must pass the same human approval boundary.

## Decisions and invariants

Blueprint requirements and adopted defaults are authoritative: one candidate initially; local UUID identities; versioned records; UTC events; preserved date precision; unknown is distinct from false/zero/known-empty; candidate-approved evidence; runtime data outside source control; equal inclusion rules for JSON/RAG; retained referenced versions. The story split, proposed file names, SQLite layout, CLI syntax, version allocation, and internal draft records below are **implementation proposals**, not new user requirements or claims about the candidate.

All examples use symbolic synthetic identities: `C`, `F-parent`, `F-a`, `F-b`, and `V1`–`V3`. Implementation fixtures must map identity labels to synthetic UUIDs and supported version strings. Text such as `CLAIM_A` is a test marker. Neither existing fixtures nor these examples supply real candidate history, proficiency, authorization, employers, salary, or approval.

Resolve the following decisions in their owning stories and record the outcome in the future `docs/components/PROFILE-01.md`. A blocking decision must be settled before its dependent implementation is considered complete; leaving a decision in this table is not permission to guess candidate facts.

| ID | Decision / observed gap | Proposed direction and resolution owner |
|---|---|---|
| D01 | Candidate/fact identities and profile-version namespace | Persist one candidate UUID; assign fact UUIDs independently of text/hashes. Corrections retain identity; different assertions receive new identities. Allocate unique opaque profile-version strings, preferably UUID-backed, plus an explicit sequence/predecessor for ordering. Enforce unambiguous C08 lookup without adding a multi-user system. S01/S03/S04. |
| D02 | C01 unknown eligibility and policy separation | Current `remote_eligible=True` and default empty collections cannot represent all unknown states safely. `target_locations` mixes eligibility/willingness and `min_salary` is a preference. Resolve a FND-coordinated versioned representation that preserves unknowns and keeps desired-job criteria with C02. Do not reinterpret old v1 fields silently or substitute false/empty for unknown. S01, with FND-01/POLICY-01 ownership recorded. |
| D03 | Date, schema and UTC validation | Current `end_date=None` is described as ongoing, whereas blueprint null means unknown. Distinguish an explicit ongoing assertion from an absent end date. Retain year/month/day precision; define calendar and partial-date consistency checks without fabricating boundaries. Explicitly validate supported schema versions and UTC events; the current base version string and aware datetime alias alone do not enforce them. S01. |
| D04 | Provenance model and evidence retention | Proposed immutable profile-local provenance records, addressed by stable source revision IDs through C01's provenance reference. Preserve source type, locator/section, hash where bytes exist, capture time, and candidate attestation where no document exists. Link eligibility assertions to provenance too. Decide which metadata must travel in C01 versus the local catalog through FND change discipline. S01/S02/S03. |
| D05 | Inclusion vocabulary, defaults and mandatory context | Proposed purposes: `assessment`, `cv`, `cover_letter`; explicit `[]` means no downstream use. Omitted permissions require review, not current allow-all defaults. Freeze rule version and approved permissions with each publication. Decide safe behavior when required parent/chronology/eligibility context is restricted; proposed visible conflict, never permission widening. S01/S05. |
| D06 | Persistence and immutability boundary | Proposed authoritative compact C01 payload/history in SQLite, large evidence bytes under `profiles_dir`, insert-only published records, detached reads. Define application-level versus database-level enforcement; do not claim tamper-proof storage. S02. |
| D07 | Approval, publication retries and current version | Proposed approval binds an exact draft revision/digest and base profile version. A retry of the same approved operation returns its original result; changed input requires a new approval/version. Select latest through an explicit atomic current pointer; reject stale-base publication instead of silently overwriting newer work. S04. |
| D08 | Historical readability versus permission for new use | Historical C08 audit resolution remains available after correction/removal/restriction. It never grants a new operational use. Proposed default: new work uses the current approved snapshot; requesting withdrawn historical evidence for new work requires a separately defined authorization path. Decide how later GEN-02 handles already-frozen work and explicit permission withdrawal; do not implement that worker here. S05/S06; hand off frozen-work policy to GEN-02. |
| D09 | Operator interface and real inputs | Proposed small local CLI over the profile service; explicit review/approval, history and versioned inspection. Final command names, exit codes, review presentation and output-file behavior belong to S07. Real candidate inputs/approval remain a separate integration dependency, not a blocker to synthetic component verification. |

Any shared contract change follows blueprint §8: compatible additions update generated schemas, fixtures and recorded versions; incompatible changes require a migration/consumer plan and an updated blueprint decision. Every schema version previously published by PROFILE-01 must remain readable and its C08 references resolvable across upgrades, with original payloads preserved. Unsupported-version errors apply to unknown/external versions, not a reason to abandon published history. A profile-only wrapper may enforce stricter publication checks, but must not hide semantics that downstream C01 consumers require. Do not publish a lossy C01 merely to avoid a necessary contract change.

## Ordered story map

Every story is **PLANNED**, belongs to PROFILE-01, and depends on the implemented FND-01/DATA-01 baseline. References to later components are consumer obligations, not prerequisites to implementing those whole components.

| Order | Story | Deliverable | Internal dependencies |
|---|---|---|---|
| 1 | [PROFILE-01-S01](#profile-01-s01) | Profile invariants, domain records and contract compatibility decisions | None |
| 2 | [PROFILE-01-S02](#profile-01-s02) | Durable profile/provenance storage and additive migration | S01 |
| 3 | [PROFILE-01-S03](#profile-01-s03) | Manual draft intake, stable fact IDs and provenance validation | S01, S02 |
| 4 | [PROFILE-01-S04](#profile-01-s04) | Explicit approval and atomic immutable C01 publication | S02, S03 |
| 5 | [PROFILE-01-S05](#profile-01-s05) | One purpose-aware inclusion boundary for both context paths | S01, S04 |
| 6 | [PROFILE-01-S06](#profile-01-s06) | Version history, diffs and exact historical fact resolution | S04, S05 |
| 7 | [PROFILE-01-S07](#profile-01-s07) | Local operator workflow and minimal CLI wiring | S03–S06 |
| 8 | [PROFILE-01-S08](#profile-01-s08) | Integrated verification and PROFILE-01 handoff | S01–S07 |

Owned paths below are proposed targets. Paths already owned by FND-01/DATA-01 are explicitly identified as coordinated changes, limited to what PROFILE-01 needs. Do not create duplicate contract definitions, a second migration runner, or placeholder implementations of later components.

<a id="profile-01-s01"></a>
## PROFILE-01-S01 — Establish profile invariants and compatibility boundaries

**Objective and requirement/contract references.** Make candidate truth, approval, identity, provenance and inclusion semantics implementable before persistence/business logic. Direct: R06/R11/R15; supporting R01/R14/R16. Blueprint §§4–6/PROFILE-01, 8–10. Contracts: C01 and candidate C08; C02 separation; C09/C11/C13/C14 consumer compatibility.

**Dependencies.** FND-01 (especially S02/S03/S07), DATA-01 handoff; no internal story dependency. Resolve blocking C01 representations before S02–S05 rely on them.

**Owned files.** New `src/job_automation/profile/__init__.py`, `models.py`, `validation.py`, `errors.py`; `tests/profile/__init__.py`, `test_validation.py`; `tests/fixtures/profile/README.md`; decision/interface sections of future `docs/components/PROFILE-01.md`. Coordinated only as required: `contracts/profile.py`, `primitives.py`, `evidence.py`, `interfaces.py`, public exports and schema exporter; generated affected schemas (including embedded C01 definitions in C09); affected contract fixtures/generator/tests; blueprint decision entry and FND handoff compatibility note. Do not globally redesign unrelated contracts.

**Inputs → outputs.** Current C01/C08 definitions, blueprint invariants and observed gaps → versioned internal draft/provenance/approval specifications, supported-version rules, safe error results, profile-service signatures and an explicit contract migration/consumer plan. Proposed service operations cover draft validation, publication, exact snapshot reads, history, inclusion and C08 resolution; names become final here without implementing their workflows.

**Tasks.**

1. Separate proposed/draft records from published approved C01. An imported `is_approved=true`, document presence, or valid Pydantic object is not an approval event. Persisted internal envelopes carry their own schema version.
2. Resolve D01–D05 and D08's interface distinction. Define candidate/fact identity scope, revision semantics, allowed-use vocabulary, provenance links, exact parent relationships and deterministic ordering. Validate duplicate IDs, foreign/missing parents, permitted parent kinds, self-reference and cycles.
3. Reconcile unknown eligibility, preference fields, null/ongoing dates, UTC events and schema-version handling through explicit contract decisions. Unknown proficiency/authorization must be representable in a published snapshot. Do not require invented values to satisfy v1 defaults.
4. Define fact-level and eligibility provenance, approval of the exact included content, and inclusion-rule version capture. If external metadata is necessary to interpret C01, define how consumers obtain the immutable companion record; otherwise coordinate a shared addition.
5. Specify safe validation errors containing codes/field locations rather than candidate payloads. Structural validation and traceable provenance do not prove semantic truth; human review remains required.
6. Keep schemas generated from typed models. Record which rules are schema-expressible and which require profile/storage validation. Plan legacy C01 reading and re-review of ambiguous old values without rewriting historical bytes.

**Acceptance examples.**

- A draft missing authorization, language proficiency and remote eligibility retains explicit unknowns; it cannot become a positive remote assertion through a default. Desired salary is not converted into candidate capability.
- A synthetic month date `2021-05` remains month precision. Missing end date does not assert ongoing employment. Invalid full calendar dates fail without inventing replacements.
- Duplicate `F-a`, an absent `F-parent`, a cyclic parent relationship, unsupported use `automatic_application`, or unsupported schema version produces a specific safe error.
- A supported legacy fixture remains inspectable under its recorded schema; ambiguous values can block new publication pending review without blocking historical inspection. Every previously published PROFILE version still resolves after upgrade. Unknown external schema versions fail explicitly; no migration guesses what omitted fields meant.

**Tests.** Add `tests/profile/test_validation.py` for the above cases, unknown/false/known-empty distinctions, parent integrity, approved-versus-draft separation and safe errors. Extend affected `tests/contracts/` checks for exact wire/schema compatibility and old fixtures. Synthetic inputs only; no external services.

**Native Windows verification.** Run the targeted validation and affected contract tests using `.\.venv\Scripts\python.exe`; verify UTF-8 synthetic provenance/claims and precision-date round trips. Record Windows/Python versions and UTC handling. Importing `job_automation.profile` must create no files or service calls.

**Migration/configuration impact and handoff.** No database migration yet. Record chosen internal/shared schema versions, compatibility obligations, public signatures, fixture ownership and any FND-coordinated changes. No real profile defaults enter config.

**Unresolved decisions.** Close D01–D05's wire/model decisions and supported-version policy here. D06/D07 operational mechanics follow in S02/S04. Resolve shared meaning changes with FND ownership; a locally convenient lossy representation is not an acceptable fallback.

<a id="profile-01-s02"></a>
## PROFILE-01-S02 — Add durable profile and provenance storage

**Objective and requirement/contract references.** Persist complete approved versions and their evidence references without overwriting history. Direct R06/R11/R15; supporting R09/R14/R16. Blueprint §§3–5, 6/PROFILE-01 and DATA-01, 8–9. Contracts: C01, candidate C08; C11/C13/C14 references inform retention.

**Dependencies.** FND-01, DATA-01; S01's identities, records and compatibility decisions.

**Owned files.** New `src/job_automation/storage/repositories/profiles.py`, `src/job_automation/profile/evidence_store.py`, `tests/profile/test_repository.py`, `test_evidence_store.py`. Minimal coordinated edits to `storage/migrations.py`, `engine.py`, repository/package exports, `tests/storage/test_migrations.py`, `tests/test_cli_storage.py`; storage/ownership sections of the PROFILE handoff. DATA-01 retains ownership of generic storage machinery.

**Inputs → outputs.** Validated versioned draft/provenance records and C01 payloads → durable draft revisions, stable identity records, immutable provenance revisions, published snapshot payloads/membership, ordered version metadata and current-pointer storage. Repository reads return validated detached values plus explicit missing/corrupt/unsupported-version outcomes.

**Tasks.**

1. Append the next migration (currently 3) using DATA-01's runner. Preserve checksums and SQL for migrations 001/002. Cover candidate/fact identity scope, draft revisions, version uniqueness, snapshot membership, provenance links, history and current-pointer integrity with minimal tables/constraints.
2. Store compact authoritative snapshot data in SQLite; do not reconstruct old C01 from mutable current facts. Provide insert-only publication operations. A duplicate version key with different content fails; no `REPLACE`/update path silently changes approved payloads.
3. Ensure publication repository operations participate in one caller-owned transaction. Existing methods using nested `with self.conn:` are not proof of composable atomicity. Avoid inner commits that expose half a snapshot/history/current-pointer update.
4. Store bulky evidence under resolved `profiles_dir` using generated safe identities, hashes and immutable revisions. Finalize a complete evidence file before committing a database reference. Document interrupted staging/orphan behavior; a failed write must not publish a dangling reference. Do not repurpose raw/artifact overwrite methods.
5. Resolve all persisted evidence paths against the configured profile root. Reject escapes, reserved/unsafe names and alias collisions; do not use candidate names or provenance text as filenames. Preserve a human-readable locator as private metadata.
6. Return detached validated snapshots so changes to caller lists/dicts cannot affect saved data or cached reads. Preserve fact text/precision/provenance/permissions exactly. No profile deletion or retention sweep is exposed in this component.
7. Keep the migration simple: the existing runner splits SQL at semicolons. If database triggers are chosen, explicitly coordinate the runner change and tests; do not assume compound trigger bodies work unchanged. Update existing tests that hardcode latest database version/count 2.

**Acceptance examples.**

- Upgrading a populated v2 database adds profile storage, preserves existing runs/jobs/requests and migration checksums, and a second migration invocation applies nothing.
- Saving `V1`, closing the engine and reopening returns the same snapshot and provenance. Saving altered content under `V1` fails and leaves the original intact.
- Injected failure after snapshot insertion but before history/current update rolls back all publication rows. Evidence-file failure cannot yield a published snapshot; an orphan staged file is identifiable without deleting referenced evidence.
- Mutating a returned `evidence_records` list or eligibility dictionary cannot change a subsequent read. Evidence filename collisions and attempts to escape `profiles_dir` fail safely.

**Tests.** `test_repository.py`: version uniqueness, exact round trips, detached reads, no delete/update exposure, rollback and reopen. `test_evidence_store.py`: hashes, containment, source revision preservation, write failure and missing/tampered-file outcomes. Extend migration/CLI regression tests with populated-v2 upgrade and failure rollback.

**Native Windows verification.** Exercise an external data root containing spaces/umlauts, two process lifetimes, close/reopen and lock release. Run migration twice from PowerShell with the explicit interpreter. Test interrupted writes and path handling on Windows; portable path tests alone do not satisfy this story.

**Migration/configuration impact and handoff.** Add one forward migration unless S01 compatibility work proves more necessary. Reuse `ResolvedPaths.profiles_dir` and `database_path`; no new service. Record tables, transactional boundaries, file staging/recovery behavior, immutability enforcement limits and pending OPS-01 retention/backup integration.

**Unresolved decisions.** Close D06: exact table/key layout, canonical serialization/hash rules, draft storage, file finalization and orphan reporting. Decide application-only versus database enforcement honestly. Runtime power-loss durability must not be claimed solely from process rollback tests or existing WAL settings.

<a id="profile-01-s03"></a>
## PROFILE-01-S03 — Ingest reviewable facts with stable IDs and provenance

**Objective and requirement/contract references.** Turn manually supplied candidate material into validated, reviewable drafts while preserving identity and source lineage. Direct R06/R11/R15; supporting R01/R14/R16. Blueprint §§4/C01, 5/draft accuracy, 6/PROFILE-01, 10/candidate inputs. C02 remains separate; C08 informs fact identity.

**Dependencies.** FND-01, DATA-01; S01 and S02.

**Owned files.** New `src/job_automation/profile/intake.py`, `provenance.py`, `tests/profile/test_intake.py`, `test_provenance.py`, synthetic intake fixtures under `tests/fixtures/profile/`; extend S01 validation/models and S02 repository only for this workflow. Document intake format and identity rules in the PROFILE handoff.

**Inputs → outputs.** Explicit local structured manual input, optional evidence files/candidate attestations, and optionally an existing draft/base version → persisted unapproved draft revision, assigned/preserved UUIDs, immutable source metadata and record-level validation/review issues. No C01 is published at intake.

**Tasks.**

1. Implement one explicit structured manual-input format. User-supplied source documents may be attached as provenance without automatically parsing or extracting claims. No DOCX/PDF/OCR or model dependency is needed.
2. Allocate a candidate UUID once and fact UUIDs once. A correction explicitly targets the existing fact; an unrelated assertion receives a new ID even if text resembles another fact. Hashes track revisions/deduplication hints, not permanent identities. Preserve IDs across draft retries and later approved versions.
3. Define import retry identity or explicit existing-draft revision input so retrying the same operation does not multiply facts. Do not silently merge distinct facts based on title, text, source filename or similarity. Reject accidental reuse of an ID for an unrelated fact/candidate.
4. Capture source type, immutable source revision/hash where available, source locator, import/capture time and attribution. Preserve original and edited proposed text. Candidate attestation is an explicit source type, not a fabricated document. Trace eligibility fields to reviewed supporting assertions/catalog entries.
5. Validate kinds, dates, parent relationships, claims/skills/metrics, provenance and explicitly proposed allowed uses. Missing source or ambiguous input remains a review issue. Do not infer language, work authorization, dates, metrics or ability from policy/defaults.
6. Ignore/reject imported approval assertions as authority; input text cannot run commands or choose tools. Local LLM proposals, if added later, enter this same unapproved intake path. Preserve rejected/superseded draft decisions for inspection without making them eligible evidence.

**Acceptance examples.**

- Retrying synthetic import operation `I1` yields the same draft and `F-a`. Correcting `CLAIM_A` to `CLAIM_B` explicitly retains `F-a`; a different assertion receives `F-b`.
- Two unrelated synthetic records with identical headlines remain separate until a human resolves them. Changing a source filename does not generate a new fact identity.
- An input containing `is_approved=true` and instruction-like text remains unapproved and inert. A draft with omitted proficiency cannot acquire a value from the existing synthetic C01 fixture.
- A source document replaced on disk produces a distinct provenance revision; prior source metadata remains available. An explicit candidate attestation needs no invented attachment/hash.

**Tests.** Cover duplicate retries, corrections/new identities, invalid cross-candidate references, source hash/revision behavior, attestation, missing provenance, permission omission, parent graphs, unknowns and safe field-level failures in the two owned test modules. Assert no publication or current-pointer change from intake.

**Native Windows verification.** Import a UTF-8 synthetic draft and evidence from a path containing spaces/non-ASCII characters, reopen it in another process, and verify stable IDs and unchanged byte hashes. Exercise a locked/missing input file and malformed JSON with safe diagnostics. No service credentials are needed.

**Migration/configuration impact and handoff.** Use S02 tables and profile-root storage; any additional persistent field requires a forward migration, not edits to applied SQL. Record supported input format, relative-path base, retry key, ID correction rules and provenance availability semantics.

**Unresolved decisions.** Close D01/D04 intake mechanics: import-operation identity, explicit correction/new-fact controls, attachment copying policy, required source locators and how review decisions are retained. Actual candidate facts are still unsupplied and must not be filled from examples.

<a id="profile-01-s04"></a>
## PROFILE-01-S04 — Publish explicitly approved, immutable C01 snapshots

**Objective and requirement/contract references.** Bind human approval to exact content and publish one durable, immutable profile version per approved change. Direct R06/R11/R15; supporting R09/R14/R16. Blueprint §§4/C01, 5/persistence and security, 6/PROFILE-01, 8. C08/C11/C13/C14 depend on stable version meaning.

**Dependencies.** FND-01, DATA-01; S02/S03 and S01 compatibility decisions.

**Owned files.** New `src/job_automation/profile/approval.py`, `service.py`, `tests/profile/test_publication.py`; narrowly extend profile repository/models and synthetic publication fixtures. Record approval and publication behavior in the handoff.

**Inputs → outputs.** Reviewed draft revision/digest, expected base profile version, explicit candidate approval identity/event and idempotency key → approved C01, immutable version/history metadata and atomically updated current pointer; otherwise a safe validation/conflict/storage result with the draft still inspectable.

**Tasks.**

1. Present/identify the exact proposed fact set, eligibility, provenance and permissions being approved. Require a deliberate approval operation; do not approve through import, validation, a model, or default CLI behavior. Bind approval to a draft revision/digest so later edits invalidate it.
2. Revalidate publication invariants, supported schemas, parent/provenance integrity and source readiness. Only explicitly approved records and eligibility enter C01; deferred/rejected proposals remain outside it. Record the approver and UTC event without implying cryptographic identity verification.
3. Allocate a unique version and monotonically ordered history entry. Approved changes to content, dates, provenance, membership, permissions or inclusion rules create a new version. Record predecessor and change summary; fact identity is independent of the version.
4. Publish payload, membership, approval metadata, version metadata and current pointer in one transaction. Use expected-base/draft revision checks to reject a stale competing review. Do not rely on a future RUN-01 process lock for correctness.
5. Make publication retries idempotent: the same operation/digest returns the same version and original approval timestamp. Same key with changed content conflicts. Specify no-op resubmission behavior separately from a deliberate newly approved version.
6. Support removing or correcting a fact in a new version without mutating/deleting previous versions. An old snapshot containing an excluded/private approved fact can remain stored for local audit, with downstream use governed by S05.

**Acceptance examples.**

- Approving draft revision `D1` creates `V1`; editing it to `D2` before approval is applied causes a stale-review failure. Neither the imported approval flag nor a successful validation can publish `V1`.
- `V2` corrects `F-a`, changes `F-b` to `allowed_uses=[]`, and omits another previously included fact. `V1` retains every original value; current reads select `V2` only after successful commit.
- A retry returns `V2` with unchanged history count/approval event. Reusing its operation key with changed payload fails. Two publications based on `V1` cannot silently overwrite one another's current pointer.
- An injected failure between snapshot/history/current writes leaves no new visible version and preserves the previous current snapshot. A caller mutation after approval cannot alter stored `V1`.

**Tests.** `test_publication.py`: explicit approval, draft binding, unapproved/rejected fact exclusion, UTC metadata, version creation, same-ID corrections, permission/provenance changes, no-op/retry/conflict semantics, stale-base race, rollback and restart recovery. Use distinct connections/processes where needed to test the transaction boundary.

**Native Windows verification.** Run publication and rollback tests against a real temporary SQLite file. Publish in one subprocess and read in another, then force a process interruption during publication and verify old-or-complete-new visibility after reopen. Record process-crash evidence separately from untested power-loss behavior.

**Migration/configuration impact and handoff.** Use S02's schema; add only explicit forward migrations if required. Document current-version lookup, approval/retry keys, serial ordering and error mapping. No Salesforce state or C13 worker transitions are changed.

**Unresolved decisions.** Close D07: approval presentation/event format, exact base-version conflict handling, version allocation and no-op rules. Record whether an explicitly approved empty evidence set is allowed; missing eligibility remains unknown regardless. Real candidate approval is not supplied by synthetic tests.

<a id="profile-01-s05"></a>
## PROFILE-01-S05 — Expose shared inclusion rules for JSON and RAG consumers

**Objective and requirement/contract references.** Give both future context paths the same eligible evidence universe for the same approved snapshot and intended use. Direct R06/R11/R15; supporting R01/R14. Blueprint §§4/C01/C09, 5/assessment and retrieval, 6/PROFILE-01 and CONTEXT-01–04. C08 references remain attached to included facts.

**Dependencies.** FND-01, DATA-01; S01 and S04. CONTEXT-01–04 are future consumers, not implementations to add here.

**Owned files.** New `src/job_automation/profile/inclusion.py`, `tests/profile/test_inclusion.py`, `tests/fakes/profile_consumers.py`; extend public profile service/model interfaces and synthetic permission fixtures. Changes to shared `ContextSelector` belong to an explicit FND/CONTEXT compatibility decision if needed, not an unrecorded signature edit.

**Inputs → outputs.** Approved snapshot/version, explicit intended use and its frozen inclusion-rule version → deterministic ordered eligible facts/IDs, eligible mandatory eligibility/chronology and parent context, plus safe exclusion/conflict metadata. Output is a profile view, not a C09 builder, chunk set or retrieval result.

**Tasks.**

1. Centralize `assessment`/`cv`/`cover_letter` permission interpretation and snapshot approval checks. Reject unknown uses; explicit `[]` excludes all downstream use. Missing permissions follow S01 review rules, never an implicit allow-all conversion.
2. Apply the same rule implementation and frozen rule version to both consumer paths. Preserve deterministic ordering, fact IDs, source-version association and parent links. Filter before any downstream embedding/model input; private evidence must not leak through strings, warnings or metadata.
3. Define mandatory eligibility/essential chronology and parent inclusion under the same permissions. Mandatory status and parent expansion cannot widen allowed uses. If mandatory content cannot be provided safely, return an explicit conflict and no usable operational view. Only optional context may be omitted with a documented warning; never silently include restricted content or drop mandatory context.
4. Keep candidate truth separate from preferences and job-specific relevance. No skill matching, top-k selection, chunking, prompt building, token budgeting or index construction belongs here. A retrieval miss later is not evidence of absent capability.
5. Define active operational use separately from historical audit/replay. Historical resolution is not an authorization bypass. Preserve old permission metadata for inspection; document D08's handoff for new work and already-frozen requests.
6. Give CONTEXT-01/02/04 a precise integration contract, including intended-use propagation despite the current selector's missing argument. Tests use small consumer fakes that call this real inclusion boundary; the existing all-facts `FakeContextSelector` does not prove inclusion correctness.

**Acceptance examples.**

- For `V1`, `F-a` allowed only for assessment appears in both consumers' assessment input universe and neither CV universe. `F-b` with `[]` appears in no operational view.
- Same snapshot, purpose and rule version yield the same ordered eligible IDs and mandatory context in both fake consumers. Later RAG selection may legitimately choose fewer IDs; equality of final retrieved output is not required.
- An allowed child beneath a restricted parent cannot reveal the parent's title, dates or claims through expansion. If that parent supplies mandatory chronology, both consumers receive an explicit conflict and no usable view. Only optional context can receive the documented omission outcome.
- Unknown eligibility stays unknown. A newer permission change produces a new version; it does not rewrite the old snapshot, and C08 lookup cannot be used as permission for new generation.

**Tests.** `test_inclusion.py`: purpose matrix, approval checks, explicit-empty/missing permissions, unsupported purposes, deterministic order, parent/mandatory privacy conflicts, unknowns, version-bound rules and parity through two consumer fakes. Assert excluded text markers are absent from every operational output field, not just the fact-ID list.

**Native Windows verification.** Run parity tests against snapshots read from the real SQLite repository at a Unicode/space path. Close/reopen and verify ordering and eligible content remain stable. No Ollama, embeddings or network requests are needed.

**Migration/configuration impact and handoff.** Freeze any inclusion metadata with the snapshot using S01/S02's agreed representation. No mutable global config may silently reinterpret old snapshots. Hand off the shared API and purpose propagation to CONTEXT-01/02/04, MATCH-01 and GEN-02.

**Unresolved decisions.** Close D05: required chronology/eligibility definition, safe restricted-parent behavior, rule-version evolution and output shape. Close PROFILE's D08 operational-versus-audit behavior; record the separate decision required of GEN-02 for withdrawn permission on already-frozen work.

<a id="profile-01-s06"></a>
## PROFILE-01-S06 — Provide history and resolve facts from older snapshots

**Objective and requirement/contract references.** Keep every published version inspectable and resolve exact old citations after edits, removals or permission changes. Direct R06/R11/R15; supporting R09/R14/R16. Blueprint §§4/C01/C08, 5/retention and draft accuracy, 6/PROFILE-01 and GEN-02/04. C11/C13/C14 are reference consumers, not workflows to implement.

**Dependencies.** FND-01, DATA-01; S04/S05 and S02's durable provenance.

**Owned files.** New `src/job_automation/profile/history.py`, `references.py`, `tests/profile/test_history.py`, `test_references.py`; extend repository read methods/service exports and synthetic multi-version fixtures. No mutation of assessment/request/artifact workflows is owned here.

**Inputs → outputs.** Candidate/current or exact version selectors; two versions for comparison; typed candidate C08 `(profile_version, fact_id)` → ordered history, immutable snapshot/diff, or exact fact plus original provenance/permissions. Missing version, fact absent from that version, corrupt payload, unknown external schema, and unavailable source bytes are distinct safe outcomes. All schemas previously published by PROFILE-01 remain supported for exact historical reads.

**Tasks.**

1. List versions in recorded sequence with predecessor, UTC approval metadata, content/rules version and safe change summary. Select current explicitly; never infer order from lexical version strings or filesystem timestamps.
2. Compare versions by stable fact ID: added, changed, removed, provenance-changed and permission-changed; include eligibility changes. A correction is distinguishable from removal plus a new fact. Detailed private diffs require an explicit local inspection operation.
3. Resolve C08 against exact snapshot membership. `V1/F-a` returns `V1`'s original fact even if the latest `F-a` differs or is absent. No fallback to latest, same-ID records in another version, search results or nearest text.
4. Enforce D01's unambiguous version namespace/candidate scope. A well-formed UUID/reference is not proof it exists. Reject job evidence through this candidate resolver; job C08 belongs to the posting owner.
5. Preserve original provenance metadata and source revision links. Missing/tampered optional source bytes produce an explicit availability/integrity result while the stored fact/metadata remains inspectable; never replace them with newer source bytes or claim source verification succeeded.
6. Retain all published profile versions/facts and referenced provenance in this component. Expose retention/backup inventory information for OPS-01 if needed; do not assume existing C11 text/C13 JSON fields provide foreign-key protection. No hard-delete, purge or backup system is implemented here.
7. Keep local audit access separate from S05's operational permission checks. History can explain an earlier draft without approving new use, claiming a paraphrase true, or mutating frozen request inputs.

**Acceptance examples.**

- `V1/F-a=CLAIM_A`; `V2/F-a=CLAIM_B`; `V3` omits `F-a`. After restart, `V1/F-a` and `V2/F-a` resolve their own text, dates, permissions and provenance; `V3/F-a` returns fact-not-in-version.
- An unknown version returns version-not-found even when `F-a` exists elsewhere. A job C08 cannot be coerced into a candidate reference.
- Permission restriction in `V2` leaves `V1` audit-readable but does not permit an unrestricted new CV operation. A fake C13 consumer retaining `V1` still resolves `V1`, and stored C11/C14 reference values are unchanged.
- Removing an external original source file does not erase the preserved historical fact. Source availability is reported truthfully; changed external bytes do not replace the approved source revision.

**Tests.** Multi-version lifecycle tests in `test_history.py`/`test_references.py`; exact membership, correction/removal/restriction, version ordering, diff classification, provenance revisions, source failures, missing/corrupt versions, unknown external schemas and candidate/job discrimination. Preserve fixtures for every previously published schema and resolve their old C08 references after upgrade. Use test-only consumers for C11/C13/C14 and verify no latest fallback across process restart.

**Native Windows verification.** Create V1–V3 through the real service, terminate the process, then resolve both older versions in a new PowerShell-launched process using an external Unicode data root. Check closed file handles and safe missing-source diagnostics. Record actual bytes/IDs compared using synthetic data only.

**Migration/configuration impact and handoff.** History and snapshot payloads remain append-only. No retention duration is configured. Document resolver signatures/errors, exact-version requirements and the list of data OPS-01 must preserve; notify GEN-02/04 and CONTEXT owners of the historical-access contract.

**Unresolved decisions.** Close history pagination/order and diff presentation details, provenance availability response shape, and retention inventory shape. D08's permission decision must be documented alongside the resolver; any future destructive erasure policy is separate work and cannot silently break this acceptance.

<a id="profile-01-s07"></a>
## PROFILE-01-S07 — Wire the native Windows operator workflow

**Objective and requirement/contract references.** Make intake, review, approval and exact historical inspection usable through the existing local application. Direct R06/R11/R15; supporting R14/R16. Blueprint §§3, 6/PROFILE-01, 8–9. C01/C08 are operational inputs/outputs; C02 configuration remains independent.

**Dependencies.** FND-01, DATA-01; S03–S06.

**Owned files.** New `src/job_automation/profile/cli.py`, `tests/test_cli_profile.py`, `tests/fixtures/profile/cli/` synthetic examples; minimal registration in existing `src/job_automation/cli.py`; README profile usage and PROFILE handoff command documentation. Modify `configuration.py`/config schema/examples only if a necessary setting cannot be represented through existing resolved paths/service arguments.

**Inputs → outputs.** Explicit input/config/data-root paths, draft/base/version/fact selectors and deliberate candidate approval → safe status/IDs, local review presentation, history or requested snapshot/fact export. Invalid/conflicting operations return documented nonzero exit codes without publishing partial state.

**Tasks.**

1. Add a small profile command group delegating to the service. Proposed actions: `import`, `review`, `approve`, `history`, `show`, `resolve`; select exact syntax in D09. Review must show the content and permissions of the identified draft revision; approval must identify that same revision/digest.
2. Use existing `--config`/`--data-root` behavior and `ResolvedPaths`; explain each relative input/output path base. Commands must work with absolute paths from another working directory and need no activated environment.
3. Keep ordinary success/error output to safe status, codes and identifiers. Explicit local review/show/export may reveal requested private facts, but logs, tracebacks and error serialization must not dump facts, evidence text, approval notes or sensitive source locators. Do not reuse raw exception printing as a privacy guarantee.
4. Store real inputs, drafts and exports outside the checkout. Prevent accidental overwriting of snapshots/evidence during export, and require explicit output targets where appropriate. Commit only visibly synthetic examples; the current C01 fixture is never a production default.
5. Reject approval attempts for invalid/stale drafts; no implicit approve-on-import or approve-on-export behavior. Help exposes only implemented commands. No real candidate is initialized from test fixtures on first run.
6. Document complete create/review/approve/correct/history/resolve usage with placeholder identities and expected exit categories. Preserve existing configuration/storage CLI behavior through regression checks.

**Acceptance examples.**

- A synthetic import command reports an unapproved draft ID, review identifies its exact revision, and an explicit approval publishes `V1`. Import alone leaves current profile unchanged/unset.
- From `$env:TEMP`, absolute interpreter/config/input paths work against a data root named `PROFILE-01 Prüfung ä`. Relative data roots and runtime exports inside the repository are rejected according to the documented boundary.
- Invalid input containing `PRIVATE_PROFILE_MARKER` causes a nonzero exit without the marker, source text or traceback in ordinary stdout/stderr. Explicit local review can display the requested synthetic marker without writing a diagnostic log containing it.
- After publishing `V2`, exact `V1/F-a` inspection returns original content. A nonexistent version/fact fails clearly and never prints current content as a substitute.

**Tests.** Subprocess tests in `test_cli_profile.py` for full synthetic workflow, approval separation, stale review, UTF-8 files, unknown selectors, safe outputs, export collisions, no import side effects, different working directory and exit codes. Run affected existing CLI/configuration tests; do not add unrelated CLI workflows.

**Native Windows verification.** Execute the documented workflow using the explicit virtual-environment interpreter, quoted paths, and native PowerShell. Cover checkout and different-working-directory invocations; use data/input paths containing spaces/umlauts. Capture safe output and exit codes, including missing/locked input and malformed JSON. No WSL, Docker, Word, model or Salesforce setup is required.

**Migration/configuration impact and handoff.** Prefer the stored current pointer and existing profile root over a new active-profile path setting. If configuration changes are necessary, update its schema/examples and precedence tests explicitly. Record final commands, data-path bases, exit codes and privacy behavior.

**Unresolved decisions.** Close D09: command/argument names, interactive versus file-based review, explicit approval binding, safe inspection/export defaults and conflict exit codes. The runnable documentation must reflect implemented syntax; proposed commands are not claimed to exist today.

<a id="profile-01-s08"></a>
## PROFILE-01-S08 — Verify PROFILE-01 and publish its handoff

**Objective and requirement/contract references.** Demonstrate the complete PROFILE-01 acceptance and give downstream owners an exact usable boundary. Direct R06/R11/R15; supporting R09/R14/R16. Blueprint §§6/PROFILE-01, 7–10; C01/C08 and their C09/C11/C13/C14 consumer references.

**Dependencies.** FND-01, DATA-01; S01–S07. Real candidate input and later context/generation services are not prerequisites for synthetic component verification.

**Owned files.** New `tests/profile/test_lifecycle.py`; completion of `tests/fixtures/profile/README.md`, PROFILE usage in README, and `docs/components/PROFILE-01.md`. Coordinate fixes with earlier story owners; no duplicate business implementation belongs in this verification story.

**Inputs → outputs.** Implemented profile services, migration, CLI, synthetic fixtures, contract decisions and per-story check evidence → integrated lifecycle results, native Windows evidence, documented APIs/versions/limitations, and an honest component status.

**Tasks.**

1. Run one representative lifecycle through real local storage: create unapproved draft; review/approve V1; correct one fact, restrict another and remove another in V2/V3; select permitted evidence for both fake context consumers; restart; resolve every old C08 exactly; inspect history/diffs.
2. Verify failure boundaries: stale approval, duplicate/conflicting publication, invalid parent/provenance, mid-publication failure, returned-object mutation, unsupported versions and missing source bytes. Check privacy with distinct synthetic markers in claims, provenance and errors.
3. Verify populated-v2 migration, migration idempotence/checksums, and affected contract/storage/CLI regressions. Check generated schemas against selected typed definitions and supported legacy fixtures; distinguish wire-schema validation from profile/storage invariants.
4. Execute native Windows checks below and capture actual OS/PowerShell/Python/dependency versions, commands, test counts, exit codes and path scenarios. Do not copy prerequisite success claims as PROFILE evidence or call process-crash testing a power-loss guarantee.
5. Hand off current versus exact-version access, stable fact identity/correction rules, provenance/source availability, inclusion-purpose contract, frozen rule versions, approval/idempotency behavior and OPS retention obligations. Identify pending real-input and downstream integration work explicitly.

**Acceptance examples.**

- The lifecycle proves that changing/removing `F-a` creates new versions while `(V1,F-a)` remains resolvable after restart, with its original approved content, provenance and permissions.
- Both consumer fakes receive the same eligible universe for a pinned snapshot/use/rule version. This verifies PROFILE's shared boundary; JSON budgeting, RAG retrieval quality and generated-document truth remain unverified downstream work.
- The handoff labels unit/contract, real SQLite integration, consumer-fake integration and native Windows results separately. Network/model/Salesforce checks are not applicable to this component; real candidate onboarding remains pending unless actually supplied and approved later.
- Completion does not label G1/G2, Phase 0, document generation or the entire R06/R11 requirement complete.

**Tests.** Run `tests/profile/`, `tests/test_cli_profile.py`, affected contract/storage/config/CLI checks, then the full existing suite once after the implementation stabilizes. Expand/repeat only for changed code, failures or unresolved concerns. Fixture review confirms no real facts or source documents were committed.

**Native Windows verification.** Execute the recipe below plus each story's failure/path/restart cases. A synthetic run on another OS is supplementary. `verified` requires declared acceptance including native Windows evidence; otherwise use `implemented` with explicit pending checks.

**Migration/configuration impact and handoff.** No new behavior beyond fixes needed for acceptance. Record actual database/schema/rule versions and legacy compatibility, all owned/coordinated files, decisions D01–D09, commands/results, privacy/storage limits, and next consumers: MATCH-01, CONTEXT-01/02/04, GEN-02/04 and OPS-01.

**Unresolved decisions.** Close all PROFILE-owned blockers before `verified`. Real candidate data, downstream frozen-work revocation policy and future cleanup/backup integration can remain assigned dependencies with stated limits. Missing live inputs must not be disguised as invented candidate facts or approvals.

## Native Windows verification recipe for implementation

This is a **future acceptance recipe**, not test evidence from this planning task. `tests/profile/`, `tests/test_cli_profile.py` and profile commands do not yet exist. S07 must add the actual profile command sequence after selecting its syntax. Reuse the repository's Python/pytest setup; no dependency download or application test run is required to write these stories.

Use an actual native Windows checkout and, for path verification, a checkout location with spaces/non-ASCII characters. The paths below are examples to replace with tested locations. Use a unique disposable external data root containing synthetic inputs only. Record installed versions rather than assuming the handoff's historical versions remain installed.

```powershell
$repo = 'C:\Work\Job Automation Prüfung'
$python = Join-Path $repo '.venv\Scripts\python.exe'
$config = Join-Path $repo 'config\app.example.json'
$profileDataRoot = Join-Path $env:TEMP ('PROFILE-01 Prüfung ä ' + [guid]::NewGuid().ToString('N'))
Set-Location -LiteralPath $repo

$PSVersionTable.PSVersion
[System.Environment]::OSVersion.VersionString
& $python --version
& $python -m pip show pydantic pytest tzdata

& $python -m pytest '.\tests\profile' '.\tests\test_cli_profile.py'
if ($LASTEXITCODE -ne 0) { throw 'PROFILE-01 checks failed' }

& $python -m pytest '.\tests\contracts' '.\tests\storage' '.\tests\test_cli.py' '.\tests\test_cli_storage.py' '.\tests\test_configuration.py'
if ($LASTEXITCODE -ne 0) { throw 'Affected baseline checks failed' }

& $python -m job_automation storage migrate --config $config --data-root $profileDataRoot
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
& $python -m job_automation storage migrate --config $config --data-root $profileDataRoot
if ($LASTEXITCODE -ne 0) { throw 'Repeated migration failed' }
& $python -m job_automation storage status --config $config --data-root $profileDataRoot
if ($LASTEXITCODE -ne 0) { throw 'Storage status failed' }

Push-Location -LiteralPath $env:TEMP
try {
    & $python -m job_automation config check --config $config --data-root $profileDataRoot
    if ($LASTEXITCODE -ne 0) { throw 'Configuration check from another directory failed' }
    # S07 supplies the exact implemented import/review/approve/history/resolve commands.
    # Use absolute synthetic input paths and this same external data root.
} finally {
    Pop-Location
}

# Run once after constituent acceptance checks pass and implementation is stable.
& $python -m pytest
if ($LASTEXITCODE -ne 0) { throw 'Regression suite failed' }
```

Additionally record: populated-v2 upgrade preserving existing records; unchanged 001/002 checksums; UTF-8 provenance/precision-date round trips; missing/locked/tampered evidence; draft-approval conflicts; two-process publication/reopen; interrupted publication recovery; nested-object mutation isolation; exact V1/V2 resolution after V3 removal; purpose parity and restricted-parent behavior; safe errors/exports; released Windows handles. Do not delete an existing user data directory as part of verification. Retain or remove only the identified disposable test artifacts through ordinary checked cleanup.

## Completion checklist for the future component handoff

- Record component status, objective, requirement IDs, prerequisite and actual contract/database versions, changed files, inputs/outputs and all selected decisions.
- Demonstrate deliberate approval, stable IDs, provenance, inclusion, new versions on approved change, immutable old payloads, and old C08 resolution after restart.
- Document unknown/date/permission semantics and explicit compatibility treatment of v1 defaults; do not infer candidate facts from old examples.
- Document atomic publication, retry/conflict behavior, current-pointer semantics, source-file availability, immutability limits and retention obligations.
- Separate unit/contract, real storage, fake consumer, native Windows and later live-input/integration evidence. Use `implemented` when specified checks remain pending and `verified` only when the component acceptance is demonstrated.
- Assign downstream work without implementing policy, matching, JSON/RAG builders, generation, Salesforce, OPS cleanup/backups or Phase 2 automation.

Planning result: **all eight stories remain PLANNED**. No application tests or native Windows application verification were performed by this planning task. The sole planned deliverable is this story document; real candidate facts and approval remain unsupplied.

[blueprint]: ../../IMPLEMENTATION_BLUEPRINT.md
[fnd]: ../components/FND-01.md
[data]: ../components/DATA-01.md
