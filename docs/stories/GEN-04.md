# GEN-04 — Factual/document validation implementation stories

Status: **PLANNED — documentation only; implementation and verification pending**  
Date: 31 October 2026  
Component: **GEN-04 only**, Phase 1  
Direct requirement: **R11**; supporting constraints: R06, R12, R14, R15, R16  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially C01/C08/C13/C14, §§5–9 and G4  
Repository instructions: [README.md](../../README.md) and blueprint §§8–9. No applicable `AGENTS.md` was found in the repository or checked ancestor directories.

## Objective and boundary

Validate structured C14 drafts against their exact frozen evidence and document content specification. Check reference integrity, dates, titles, verified metrics, required sections and internal consistency. Produce a durable, inspectable report that separates fatal validation errors from human-review warnings and controls whether the exact draft may proceed to rendering for review.

GEN-04 owns deterministic validation rules, review obligations, report contracts/persistence, and the minimal GEN-01 validation/render gate wiring. It does not generate or rewrite content, repair candidate evidence, retrieve additional facts, render DOCX/PDF, deliver files, change Salesforce metadata, approve documents, notify users, or implement Phase 2. A source-backed claim is traceable to supplied evidence; it is not independently verified real-world truth. Even a report with no findings requires human review before document use.

The story breakdown and proposed APIs below are implementation choices within the blueprint, not additional confirmed user requirements. All stories remain PLANNED.

## Repository evidence and dependency gates

Paths in this table are relative to `src/job_automation/` unless qualified otherwise. Current code takes precedence over older planning assumptions and handoff prose.

| Dependency / inspected evidence | Current state and consequence |
|---|---|
| **GEN-03**, direct prerequisite | **`docs/components/GEN-03.md` is absent**, despite the blueprint and configuration linking to it. The older [GEN-03 stories](GEN-03.md) are planning material, not a handoff. Current `contracts/draft_content.py`, `generation/draft_service.py`, `draft_records.py`, `draft_ports.py`, `draft_adapter.py`, `storage/repositories/draft_content.py`, migration 012 and `tests/generation/content/` implement C14 v2 generation and durable receipts. Use these real interfaces in integration tests; missing handoff/verification evidence must remain explicit. Do not recreate GEN-03 or claim its acceptance from code presence. |
| GEN-03 recipe boundary | `draft_prompts.py` implements `gen03-cv-extractive-v1` and `gen03-letter-extractive-v1`, `content-basic`/`content-compact` v1.0, and `de`/`en`. `draft_grounding.admit` requires exact factual excerpts, localized catalog headings and bounded subjective phrases. It checks allowed section order but does not require particular sections. There is no separate translated-display field or required-section minimum contract. GEN-04 must not introduce permissive paraphrasing or assume every heading is mandatory. |
| **PROFILE-01**, direct prerequisite | [PROFILE-01 handoff](../components/PROFILE-01.md) records VERIFIED with synthetic offline/native-Windows results. Inspect `profile/references.py`, `inclusion.py`, `validation.py`, `models.py`, `approval.py` and C01. Historical resolver lookup is exact by version/fact ID but does not itself enforce candidate identity, approval or purpose; GEN-04 must enforce those against the frozen envelope. Audit resolution is not authorization for new use. |
| PROFILE-01 date caveat | `DraftFact.is_ongoing` exists, but `CandidateFact` has no such field and publication does not copy it. The handoff's ongoing-date semantics therefore cannot be assumed from published C01. A null end date is unknown for this validator unless explicit approved frozen evidence supports ongoing employment. Do not recover that assertion from mutable/unapproved draft records. A future C01 extension belongs to PROFILE-01. |
| **GEN-02**, supporting prerequisite | `generation/input_service.py`, `input_records.py`, `input_ports.py`, `storage/repositories/generation_inputs.py`, schemas and `tests/generation/inputs/` exist. `StandaloneGenerationInputService` exposes `get_seal`, `reopen_freeze`, `reopen_context` and request-bound context access. **Its component handoff is absent**, so record implementation evidence separately from acceptance. Reuse this boundary; do not create another freezer. |
| Frozen input integrity | GEN-03's `draft_inputs.verify_binding` reopens frozen resources, recomputes the aggregate body/seal/recipe/context bindings, checks the material posting hash, admitted facts and rendered prompt projection, and returns `(seal, context_receipt, recipe, binding_hash)`. `DraftContentRepository.reopen` verifies stored receipt/content/audit hashes. Reuse or narrowly extract these pure verification paths without calling inference; independently validate source semantics and all C14 provenance fields. The weaker GEN-02 accessor alone is not a validation gate. |
| C14 v2 and legacy compatibility | `DraftDocumentV2` schema 2.0 has ordered sections/entries, indexed atomic claims, protected values, provenance and typed review issues; `requires_human_review` is literal true and `validation_status` is literal `pending_gen04`. `read_draft_json` retains C14 v1 reading. Preserve the immutable v2 payload and record GEN-04 results separately. Legacy content is inspectable but cannot obtain new rendering authorization by inventing missing provenance. Artifact 1.0 is unchanged. |
| C01/C08/C06 v1.0 | Candidate metrics are **strings**, not typed quantity records. C08 candidate refs contain version/fact ID, not candidate ID. Job refs contain revision/path and quote and/or span; an empty quotation can pass shape validation. C06's actual text fields include `description_clean`, `title`, `company_name_hint`. C01 has no dedicated candidate name/contact fact. Account names, policy preferences and defaults in eligibility are not new evidence. |
| **GEN-01**, consumer | `DraftValidator.validate_draft(draft, manifest)` accepts v1/v2. Coordinator requires `content_schema_versions` containing `"2.0"` for new v2 validation, but its completed-checkpoint early return precedes that capability check. `ValidationReport` still defaults `is_valid=True`, has string findings and optional hash/report ref; completed validation stores only warnings/hash. Rendering also reuses completed checkpoints/artifact slots without a bound report. Plan durable reports, explicit versioned adapters, safe diagnostics and gates on initial and resumed paths. |
| **DATA-01 / OPS-01** | Existing storage engine, transactions, migrations, checkpoints and backup/retention interfaces are supporting dependencies. Migration head inspected is **012 (`012_draft_content`)**; allocate the next migration only after inspecting implementation-time head. Persist reports locally and protect their dependency records, including GEN-03 receipts/model audits. |
| **GEN-05 / GEN-06**, downstream | GEN-05 consumes validated content and owns layout/rendering/artifacts. GEN-06 owns delivery/review integration. Supply gate and warning contracts using spies/fakes now; do not claim real rendering/delivery acceptance or G4 completion. |

## Contracts and decisions to establish first

All new persisted/exchanged records have explicit schema versions, strict parsing, detached reads and safe diagnostic fields. Names are proposed; record final names/versions in the implementation handoff. Do not silently change C14 or the existing `ValidationReport` meaning.

### Existing inputs to preserve

- `DraftGenerationReceipt` 1.0 binds one saved C14 v2 or a classified failure to request, logical key, seal, recipe, context and call; successful content has a canonical `content_hash`. Consume `DraftContentServicePort.reopen_draft(receipt_id)` or a narrow verified-read adapter, never `generate_content` as validation recovery. The GEN-03 reopen path currently needs service composition; inject a read-only wrapper over repository/binding verification so standalone validation needs no model runtime or identity-verifier invocation.
- `DraftClaim` has `source_field` and optional zero-based `source_index`. Candidate list fields (`claims`, `skills`, `metrics`) require an index; scalar fields forbid one. `ProtectedSourceValue.original_value` contains the **whole source list**, full `PrecisionDate`, scalar, or entire job text field, not necessarily the displayed excerpt. Compare that full value to the frozen field, then separately compare claim text to the selected item/date `.value`/job excerpt. Check index bounds and scalar/list types independently of schema validation.
- `DraftProvenance` includes seal, binding, context, recipe, prompt, schema, input fingerprint, model/call and receipt identities. Check every field against the verified receipts; schema shape and a recomputed draft hash do not make self-declared provenance authoritative. Validate all `frozen_inputs` labels against the manifest as well.
- C14 headings are application-generated strings indexed by section ID. Recheck exact correspondence to the pinned recipe's heading keys and language catalog. Subjective blocks must match that recipe's phrase catalog. Unknown text or added translated-display fields cannot bypass validation as merely reviewable content.

| Proposed contract | Required fields and invariants |
|---|---|
| `ValidationInputBinding` v1.0 | Request/candidate/canonical-job IDs; draft ID/version/schema/hash and GEN-03 receipt ref/hash; seal/manifest IDs/hashes; full frozen profile/job; context receipt/hash and admitted evidence IDs; requested type/purpose/language/template; content-spec ID/version/digest; rule-set ID/version/digest. Compare redundant identities and digests. This is a verified view of upstream resources, not another snapshot authority. |
| `ValidationContentRequirements` v1.0 | Explicit mapping from frozen recipe version and template/type/version/content digest to required heading keys, allowed order/cardinality, nonblank-content and evidence rules. GEN-03 currently freezes an allowed-heading spec only. Pin this supplemental GEN-04 validation policy with the ruleset at first validation; never retrofit it into the existing seal or infer requiredness from a heading list. See the proposed policy below. |
| `DocumentValidationIssue` v1.0 | Stable rule/reason code; severity `fatal` or `warning`; safe message; exact document path plus section/entry/claim IDs when available; typed evidence refs/source-field pointers; provenance of inherited warnings; review reason and suggested action. Deterministic deduplication/order. Detailed source/display comparisons stay in protected report data, not ordinary logs or remote errors. |
| `DocumentValidationReport` v1.0 | Report UUID/schema; input binding/fingerprint; validator version; per-rule outcomes (`checked`, `not_applicable`, `not_checked`) and reasons; findings; counts; `evaluation_status` (`complete` or `incomplete`); `render_decision` (`blocked` or `allowed_for_review`); `requires_human_review: Literal[True]`; explicit semantic-limit notice; UTC completion time; report content hash. Required checks cannot be `not_checked` in an allowed result. No approval status or truth score. |
| Derived gate | `allowed_for_review` iff evaluation is complete, every required rule completed, binding is intact and fatal count is zero. Compute this in trusted code, never from model output or caller-supplied `is_valid`. Warnings remain open when rendering is allowed. An operational failure with no report also blocks rendering. |
| `ValidationRunResult` v1.0 | Successful evaluation returns a complete report, including a report that blocks due to fatal findings. An execution/dependency failure returns a classified error and optional explicitly incomplete diagnostic report. No error path has a usable render authorization. Distinguish document invalidity from service failure. |
| `ValidatedDraftForRendering` v1.0 | Immutable draft payload/ref and hash, report ref/hash, complete binding, content-spec identity and persistent review obligations. A checked service constructs it only after reopening/verifying the report and draft. GEN-05 must verify the same hash before rendering; no caller-controlled Boolean can construct authority. This is local integrity control, not cryptographic human approval. |
| Service and adapter | Proposed `validate_content(draft_receipt_ref, ruleset_ref) -> ValidationRunResult`, `reopen_report(report_id)` and `prepare_render_input(report_id, draft_ref)`. Standalone operation uses injected input/content repositories without a worker, model or Salesforce connection. Add an explicit versioned port/GEN-01 adapter; preserve legacy report readers for inspection only. |

A canonical validation fingerprint covers the entire C14 payload (including headings, subjective text and warnings), draft schema/receipt, frozen body/binding hashes, context authorization, content spec and effective rule-set digest. Metadata timestamps/physical attempt IDs do not change the semantic key. Use existing canonical JSON/digest conventions with an explicit version; recompute at reuse boundaries. Keep content-spec/rule bytes or a content-addressed immutable implementation/catalog entry available for replay.

The semantic key binds the existing immutable GEN-03 receipt identity/content; it excludes only new validation-attempt IDs/times. Report hashing excludes its own hash field. State which canonical serialization is used, including GEN-02 manifest timestamp handling, rather than changing historical hash semantics. Deep-copy or reparse nested structures: a frozen Pydantic model does not make its lists/dictionaries immutable. Hashes detect accidental or partial tampering; they are not signatures proving authenticity against an actor able to rewrite the whole database and all hashes.

Validation rules are pinned on the first validation attempt, before evaluation. Retries use that exact rule set. A deliberate rule upgrade creates a new report/run and explicitly revalidates the saved draft; it never overwrites the old report or silently reuses its authorization. Changes to draft bytes require a new content identity and fresh validation. GEN-04 does not itself edit or regenerate drafts.

### Candidate and job resolution

- Candidate assertions resolve against `seal.profile_snapshot.snapshot`, with matching candidate ID and exact profile version, valid approval metadata, fact existence, frozen purpose permission and GEN-03's admitted C09 evidence membership (including mandatory facts actually supplied in context, not merely raw retrieval hits). Recheck frozen inclusion rules and ancestor privacy. A permitted child does not authorize copying a restricted parent's title, dates or organization. Do not query current profile pointers, latest permissions or active indexes. Missing pinned implementations are explicit dependency errors.
- The PROFILE-01 historical resolver may be reused through a frozen-snapshot adapter/pure helper. Do not call a repository-backed resolver and assume successful lookup alone authorizes the claim. Later P2 corrections/restrictions do not rewrite an existing P1 request; a new request freezes new authorization. Preserve any owner-provided cancellation signal without inventing a revocation workflow here.
- Job/employer assertions resolve only against the frozen C06 and the seal's exact canonical-job/revision association. Current extractive recipes require C08 `posting_revision == seal.job_snapshot.posting_revision_hash` (material hash). Verify the associated revision ID through the seal; accepting revision IDs in C08 would require an explicitly versioned future adapter. Never substitute the raw payload hash, another linked posting, live website or employer knowledge.
- Match `claim_subject` to C08 `source_kind`; split mixed candidate/job statements using GEN-03's atomic claims. A posting's requirements cannot prove candidate skills, employment, metrics or eligibility. A candidate's former employer fact cannot prove facts about the target vacancy.
- Initially allow job text paths `description_clean`, `title`, `company_name_hint`, consistent with GEN-03. Additional typed paths require a versioned resolver and documented serialization/span rules. Prohibit attribute traversal, arbitrary JSONPath, paths, URL fetches and expression evaluation. Quotes must be nonblank exact substrings; Unicode code-point spans are zero-based, end-exclusive and in bounds; quote/span must agree when both exist. Do not normalize source text or translate quotations before matching. Repeated quote matches without a span may retain traceability but get an ambiguity warning.
- Validate factual material in metadata, titles, headings, summaries, bullets, dates, metric displays and mixed motivational text. Structural coverage verifies declared bindings everywhere; text scanning only detects some undeclared assertions. Flag detected factual disguise; a `subjective` label cannot exempt a known factual assertion. Omission from RAG never proves absence of candidate capability.

### Rule and severity policy

Deterministic mismatches against required protected fields are fatal. Uncertainty in interpretation is a warning with an explicit human-review obligation; it must not be reported as a proven contradiction. Required integrity/structural checks cannot be downgraded or skipped by configuration.

| Area | Fatal validation error / blocked condition | Human-review warning / limits |
|---|---|---|
| References and binding | Missing/invalid citation, wrong source kind/version/candidate/revision, unauthorized or unadmitted fact, quote/span mismatch, missing/corrupt consumed input, unsupported C14 version or mismatched hashes. | Ambiguous repeated quotation; semantic suitability of an exact excerpt still requires review. |
| Dates | Invalid calendar date; definitely reversed range; source/date mismatch; invented precision; null converted to a supplied date; unsupported “Present”; a job observation date used as its deadline. | Partial dates with uncertain order, possible overlapping work/study, genuine source uncertainty. Concurrent roles and career gaps are not automatically errors. |
| Titles / identities | Changed protected role/title, employer, degree or target-role source value; candidate/target employer swap; unsupported identity; changed claim text, including translation, under the current extractive recipe. | Original-language title may need human interpretation; placement can imply uncertain seniority or equivalence. Do not use fuzzy title similarity to establish equivalence. |
| Verified metrics | Candidate `metrics[index]` absent/changed; job quantity inconsistent with its frozen source passage/field; altered text/value, unit, currency, period, range, sign, denominator, attribution or qualifier; invented total/rounding/conversion; structurally demonstrable transplantation to another achievement. | Exact source strings may have ambiguous scope or attribution in the assembled document. Free-text semantics cannot be completely parsed. There is no current factual paraphrase/translation allowance. |
| Required sections | Missing, duplicate or empty required section; dangling/duplicate claim IDs; required field without source binding; wrong document type/language/template identity; nonconforming declared order/cardinality. | Missing optional evidence, optional omissions, limited retrieval coverage. Never fill missing sections with invented facts. |
| Internal consistency | Conflicting protected values for the same entity/fact, section/claim disagreement, mixed candidate IDs, definite date/title/metric contradictions across occurrences, content-spec mismatch. | Ambiguous prose contradictions, apparent role overlap, repeated/redundant claims, uncertain timeline interpretation. Different roles may legitimately have different titles/metrics. |
| Subjective/review content | False review flag, loss of a required source warning after report assembly, non-catalog subjective wording, or detected unbound factual assertion disguised as subjective. | Bounded proposed motivation, source-language preservation and source uncertainty remain review-required. Recover omitted upstream warnings from frozen receipts before evaluating report completeness. |

Dates preserve source precision and unknowns. Compare partial dates as uncertainty intervals, not invented January 1 dates. A range is definitely reversed only if the earliest possible start is later than the latest possible end; intersecting intervals are uncertain, not reversed. Check actual calendar validity, including leap days, beyond the C01 regex. Current C14 claim text must equal date `.value`; `2021-03` becoming `März 2021` is not accepted as rewritten C14 content. A future GEN-05 display-format contract may localize it without adding precision, but is not implemented here. Do not use current wall-clock time to calculate experience or ongoing duration. An as-of value would need a frozen, reported source. Null end dates remain unknown because published C01 has lost the draft's ongoing flag, despite the older field description suggesting otherwise.

Metrics in current C01 are approved strings, with no per-metric independent-verification flag. Here “verified metric” means an exact member of the approved frozen fact's `metrics`, not external verification of its real-world accuracy. Require exact selection/source binding and original text under the current recipe. No locale rewrite, arbitrary tolerance, currency conversion, rounded experience total or aggregation is allowed in C14. For example, `20%` and `20 percentage points` are different; `up to 20%` cannot lose `up to`. A numeric coincidence elsewhere in the profile is not evidence. Supplemental scanning for recognizable achievement quantities in `claims`, titles or subjective content must distinguish dates, skill/version numbers and metrics. A confidently identified quantitative achievement outside an authorized metric binding is fatal (`metric_binding_missing`); uncertain classification receives a localized review warning. Do not claim this scan detects every quantity expressed in words or prose.

### Proposed required-content policy

S01/S04 will version the following initial validation policy as `gen04-extractive-v1`. These are explicit proposed technical defaults, not candidate facts or existing GEN-03 guarantees. Keys match the frozen recipe; the policy digest is separate from its existing template digest.

| Frozen template / document type | Required sections | Allowed optional sections, in recipe order |
|---|---|---|
| `content-basic` 1.0 / CV | `experience` | `summary`, `education`, `skills`; full order is summary, experience, education, skills. |
| `content-compact` 1.0 / CV | `experience` | `skills`, after experience. |
| `content-basic` 1.0 / cover letter | `experience`, `closing` | `opening` before experience; `motivation` before closing. |
| `content-compact` 1.0 / cover letter | `experience`, `closing` | None. |

Required experience contains at least one nonblank candidate claim grounded in admitted evidence; a job-only or subjective-only section cannot satisfy it. Closing contains nonblank content permitted by the frozen recipe, including a bounded subjective phrase. Every present section/entry must have valid, nonblank linked content; each required key occurs once. Candidate name/contact remains omitted with a warning for these initial templates. Education, a summary, skill lists and a salutation are not mandatory. Unsupported experience produces a fatal missing-required-content finding rather than invented history. A later student/skills-first policy must be a separate version, not an automatic fallback.

GEN-03 may currently accept a proposal that this stricter validation policy blocks, such as a letter with only experience. That is an expected validation outcome, not permission to alter a saved draft or silently call the generator again. Unknown template/digest/policy combinations block as missing configuration. Future richer upstream content specs may replace this supplemental mapping through explicit compatibility decisions; GEN-04 does not implement template design or generation changes.

Job/employer quantities use the frozen posting rather than C01 metrics. Keep employer statements distinct from estimates and candidate achievements; preserve ranges, units, currency, period and qualifications. A salary stated as annual cannot become monthly. Initially validate against supported cited text passages; adding structured compensation paths requires the versioned typed resolver described above. Source-backed posting numbers establish what the posting states, not independent verification of the employer's assertions.

### Limits of detecting misleading paraphrases

Reference validity, protected-value equality, schema checks and keyword/number scans **cannot establish that every generated sentence is entailed by its sources**. Negation, causality, scope, omitted qualifiers, team-versus-person attribution, implied seniority, skill proficiency and translation can change meaning without changing any reference or number. Multiple individually sourced clauses can also create a misleading combined impression.

Under the current recipes, “Contributed to migration” becoming “Led the migration” fails exact-source equality regardless of whether a heuristic recognizes the change. Likewise “Team reduced latency by 20%” becoming “I reduced costs by 20%” fails equality even though the number is retained. This narrow guarantee is not general paraphrase detection. Exact snippets can still be selected without surrounding qualifications, grouped under another role, or juxtaposed to imply personal ownership or causality. Catch provable structured misattribution as fatal; uncertain implications require warnings and human review. Factual translation/free paraphrase remains unsupported until a later reviewed GEN-03 recipe and GEN-04 rule version define it; do not silently admit it under these stories.

Test the limit with unchanged source text whose omitted context changes its likely interpretation, and with unfamiliar combinations for which the checker emits no localized warning. Both retain a document-wide semantic-review obligation. If future recipe fixtures explore paraphrases, label them unsupported by this release, not examples of currently renderable content. Neither absence of a heuristic warning nor exact quotation alone proves truthful presentation in context.

Baseline GEN-04 is deterministic and has no LLM dependency. Do not add an entailment model, score threshold or a second generation/repair loop to turn uncertainty into approval. Store a document-wide semantic-review obligation plus localized warnings where detectable; retain accessible original evidence for the human reviewer. Tests must include correctly bound misleading prose that is **not automatically detected**, asserting that it still carries the semantic-limit notice and cannot become approved. Detection coverage and false positives/negatives remain explicit limitations, not a promise of comprehensive deception detection.

## Rendering and processing decisions

| Validation outcome | GEN-01 / rendering behavior | Approval and review |
|---|---|---|
| Complete report with fatal findings | Persist report; validation stage fails with safe codes/report ref. No renderer/deliverer call; no ready-for-review transition. Do not drop bad claims or retry unchanged content as a semantic repair. | Content stays inspectable; no human approval is inferred. |
| Complete, zero fatal findings, warnings present | Persist/reopen bound report, then permit rendering the exact draft for review through `ValidatedDraftForRendering`. Carry all warnings and source links to the downstream review surface. | Warnings remain open; artifact approval remains `draft`. |
| Complete, zero fatal findings, no localized warnings | Same exact-content gate. Report explicitly says required checks completed and human semantic review remains necessary. | No “verified true,” “approved,” or approval notification. |
| Missing dependency, exception, incomplete checks or storage failure | Block rendering; preserve classified failure/incomplete diagnostics. Missing configuration maps to existing stage `blocked`; content/integrity failures to `failed`. Retry only recoverable execution failures under existing bounded worker policy. | No successful validation checkpoint. |
| Stale/missing/tampered report or changed content/spec/rules | Deny cached authorization. Explicit revalidation may produce a new report for legitimate new inputs; corruption requires restoration/investigation. Never treat a legacy completed checkpoint as proof. | Existing approval, if any, is not transferred to new content. |

GEN-04 completion alone does not mark a request ready for review: GEN-01/GEN-06 own later rendering/delivery/readiness sequencing. GEN-05 controls layout and safe rendering, including carrying a review-package reference without inserting private evidence or diagnostic text into the CV itself. Warnings must be inspectable before human approval; do not silently discard them after rendering. No Salesforce API calls belong in the standalone validator.

## Implementation stories

Execute S01 → S02 → S03 → S04 → S05 → S06 → S07. Source paths abbreviated as `generation/` or `storage/` are beneath `src/job_automation/`; test basenames below belong to `tests/generation/validation/` unless another path is given. Each story's tests and synthetic fixtures are part of its owned files. The shared handoff checklist applies to all seven stories; implementation writes it to `docs/components/GEN-04.md` only after recording actual results.

### GEN-04-S01 — Establish versioned validation contracts and compatibility

**Objective:** Define review-safe validation results and rendering inputs before business logic.  
**Requirements:** R11; supporting R12/R16.  
**Dependencies:** FND-01, GEN-03 contract/handoff gate, GEN-01 ports, GEN-02 access contracts.  
**Owned files:** proposed `generation/validation_records.py`, `validation_ports.py`, `validation_settings.py`; narrow changes to `generation/ports.py`, `records.py`, `contracts/export_schemas.py`; new `schemas/v1/document_validation_report.schema.json`, `document_validation_issue.schema.json`, `validation_input_binding.schema.json`, `validation_content_requirements.schema.json`, `document_validation_settings.schema.json`, `validated_draft_for_rendering.schema.json` and contract fixtures.  
**Inputs → outputs:** actual upstream C14/receipts and existing legacy report → explicit versioned contracts and compatibility adapters.

Tasks:

- Bind the contract table to existing `DraftDocumentV2` 2.0, `DraftGenerationReceipt` 1.0 and `DraftContentServicePort`. Record the absent handoff without treating existing code as absent. Add the supplemental content-requirements policy keyed to the frozen recipe/template digest; preserve upstream bytes and ownership.
- Validate derived gate invariants, typed locations/severity, required hashes, literal review requirement and rule coverage. Reject inconsistent success/fatal combinations and caller-forged decisions.
- Retain legacy C14/report readers for audit. Legacy `ValidationReport()` or a missing hash cannot authorize rendering; do not backfill hashes, sections, citations or positive results from old checkpoints.
- Define an explicit v2-capable validation adapter (`content_schema_versions = ("2.0",)`) and a durable report reference/hash result. Capability advertises support only; it is not authorization. Extend/version the existing port response with an explicit consumer migration; old `is_valid=True` fakes cannot satisfy the production gate. Leave C14 `validation_status="pending_gen04"` unchanged because the separate report owns the outcome.
- Export/register strict schemas and update affected consumer fixtures. Record incompatible changes and migration/consumer decisions in the blueprint/handoff during implementation; leave `Artifact` approval semantics intact.

Acceptance: zero-fatal complete report round-trips with human review true. A fatal issue plus `allowed_for_review`, incomplete coverage plus permission, missing hash or false review flag fails contract validation. A v1 draft/report remains readable only as legacy.

Tests: `tests/generation/validation/test_contracts.py`, `test_compatibility.py`, affected `tests/contracts/` and schema export checks. Configuration/migration impact: versioned schemas and explicit dispatch; no database change in this story.

### GEN-04-S02 — Bind and resolve evidence exclusively from frozen inputs

**Objective:** Establish evidence identity and authorization independently of generator assertions.  
**Requirements:** R11; supporting R06/R15/R16.  
**Dependencies:** S01, GEN-02, PROFILE-01, GEN-03 content/receipt adapter.  
**Owned files:** proposed `generation/validation_inputs.py`, `validation_references.py`; narrow shared frozen integrity helpers if required.  
**Inputs → outputs:** saved draft/manifest/context/seal → verified binding and resolved source map, or explicit findings/error.

Tasks:

- Reopen exact request-owned resources using GEN-03's repository verification and `draft_inputs.verify_binding` through a read-only adapter. Preserve its canonical hash conventions and add missing C14-to-receipt provenance comparisons. Check all consumed request/candidate/job/schema/options/version bindings and body hashes, not only labels. Never reconstruct context by running retrieval again or requiring the pinned model to be running.
- Implement candidate approval, exact fact lookup, purpose, admitted-ID and parent-privacy checks; validate all declared factual locations including headers.
- Implement allowlisted job paths, current recipe's exact material-hash equality, seal revision-ID association and quote/span rules. Compare candidate indexed selections and full protected source values independently. Reject all-whitespace selected text, including a span-only quotation. Treat source text as inert data.
- Carry upstream availability/override, retrieval and source warnings with origin IDs. Avoid leaking restricted evidence in diagnostics; do not query mutable profile/job/index pointers or URLs.

Acceptance: P1/J1 remains authoritative after P2/J2 becomes current. A valid P2 fact ID, unapproved P1, wrong purpose, unadmitted RAG fact, restricted parent, wrong candidate, raw-hash citation, whitespace-only quote or bad Unicode span blocks rendering. A posting-only SQL requirement cannot validate candidate SQL expertise.

Tests: `test_frozen_binding.py`, `test_candidate_references.py`, `test_job_references.py`, `test_no_mutable_reads.py`, with latest-read/network/model spies, body-tampering fixtures, bad source indexes, full-list versus selected-item comparisons and independent mutations of every provenance field. Test both stale-hash tampering and internally rehashed but semantically invalid synthetic drafts; the latter cannot bypass source checks. Configuration impact: versioned field allowlist/integrity rules only; no new profile selection or availability policy.

### GEN-04-S03 — Validate protected dates, titles and verified metrics

**Objective:** Catch factual alterations while preserving source granularity and uncertainty.  
**Requirements:** R11; supporting R15.  
**Dependencies:** S01–S02, C01 precision dates/string metrics, GEN-03 protected-value representation.  
**Owned files:** proposed `generation/validation_dates.py`, `validation_values.py`, `validation_metrics.py`.  
**Inputs → outputs:** source map and structured/display values → fatal mismatches and targeted review warnings.

Tasks:

- Apply calendar/partial-date comparison and null/ongoing rules; reuse suitable PROFILE-01 helpers without assuming they supply missing ongoing semantics.
- Compare original title/organization/credential/target fields and claim text to exact source fields. Reject factual translation/rewriting under the current recipes; prevent a target title from becoming a past candidate role. A degree title must belong to the appropriate education fact, not be inferred from a similarly named role.
- Require candidate metrics to select an exact approved source string from the cited fact; resolve job/employer quantities against the frozen posting passage. Preserve qualifiers, quantity, units, scope, period and attribution. No numeric rewrite or new structured compensation resolver is required here. Detect supported quantitative contradictions and missing metric bindings in prose as supplemental checks, with uncertainty warnings for ambiguous classification.
- Reject unsupported derivations and definite conflicts; mark unparseable semantic comparisons as limited review checks without pretending the protected-value checks were skipped or passed semantically.

Acceptance: frozen `2021-03` remains exactly `2021-03` in C14 and retains month precision in the protected value; either `März 2021` or a new day fails this recipe's claim-text check. Null end date cannot become `Present`. `Analyst` cannot become `Senior Analyst`. `up to 20%` cannot become `40%`, `20 percentage points` or an unqualified metric; the same number in another fact is insufficient. A valid original-language title passes equality but still requires review of its placement.

Tests: `test_dates.py`, `test_titles.py`, `test_metrics.py`; include leap days, mixed precision, exact German/English source strings, changed separators, ranges/negative values, currency/period swaps, number words, unsupported parsing and unrelated-fact citations. Configuration impact: exact-extraction rules and explicit parsing coverage; no tolerance/approval bypass, runtime dependency or source schema change.

### GEN-04-S04 — Validate document structure and internal consistency

**Objective:** Ensure the exact requested document meets its frozen content requirements and does not contradict itself.  
**Requirements:** R11; supporting R06/R15.  
**Dependencies:** S01–S03, GEN-03 section/claim graph and frozen allowed-heading spec, S01 supplemental required-content contract.  
**Owned files:** proposed `generation/validation_sections.py`, `validation_consistency.py`, synthetic content specs.  
**Inputs → outputs:** bound C14 and frozen content spec → structural and consistency findings.

Tasks:

- Reparse strict C14; check unique IDs across sections/entries/claims/blocks, exactly-once links, order, cardinality, required fields/nonblank content and protected-value coverage. Validate requested type/language/template metadata, exact catalog headings/subjective phrases and repeated source values across all locations.
- Implement the proposed required-content table as a pinned supplemental validation policy. Do not infer requiredness from GEN-03 `heading_keys`, require education/salutation globally, or silently treat a synthetic policy as production configuration. Verify the upstream allowed-heading digest and separate required-content digest. Production layout design stays with GEN-05.
- A required section unsupported by evidence fails with an actionable missing-content finding; optional missing facts remain omitted with warnings as specified. Never fabricate identity/contact information or require a cover letter for a CV-only request.
- Distinguish definite contradictions from plausible simultaneous roles, partial-date ambiguity and stylistic repetition. Inspect declared content language; language-detection heuristics remain review signals, not proof of proficiency or perfect translation.
- For CV role/education entries, establish a source entity from the cited fact/parent graph and compare the title, organization, dates and child achievements within that entity. A permitted child does not permit exposing a restricted parent. Two explicitly different role identities in one purported role entry, or a title from role A attached to role B's metric, is fatal when the graph proves the conflict. Ambiguous grouping is review-required. Letter paragraphs may intentionally combine separately attributed candidate and job claims; do not reject that valid structure or infer they share a source entity. A single ambiguous sentence must not be treated as proved consistent.

Acceptance: missing required `experience`, missing letter `closing`, dangling claim link and conflicting repeated dates fail. An allowed optional education omission does not fail. Two concurrent, supported roles yield at most an overlap warning. A requested German document with English source titles preserves those exact titles and localized headings, with the source-language warning; it does not assert German fluency. Moving an unchanged metric from one proved role entry to another fails attribution despite a valid citation.

Tests: `test_sections.py`, `test_consistency.py`, `test_required_content.py`; all four template/type policies, private/missing identity, empty/duplicate sections, unsupported template/language/digest, conflicting headings/entry identities, valid mixed letter paragraphs and parallel work/study. Configuration impact: version and pin supplemental section requirements alongside existing frozen content-spec IDs/digests; no templates or renderers.

### GEN-04-S05 — Preserve review warnings and expose semantic limits

**Objective:** Make review obligations visible without claiming automatic detection of misleading paraphrases.  
**Requirements:** R11; supporting R15/R16.  
**Dependencies:** S01–S04 and upstream review-issue contracts.  
**Owned files:** proposed `generation/validation_review.py`, `validation_service.py`; reviewer-facing report serialization.  
**Inputs → outputs:** rule findings, draft and inherited warnings → complete report with deterministic severity/coverage and review obligations.

Tasks:

- Merge/deduplicate inherited and new issues with provenance and stable locations. Copy source warnings independently of model claims; detect missing mandatory review flags. Preserve warning text in protected local reports and safe summaries elsewhere.
- Preserve GEN-03's `semantic_review_required`, `candidate_identity_missing`, `source_language_preserved`, subjective, posting-attribution and upstream-warning obligations as applicable. Its `translation` issue describes original-language preservation, not permission to translate facts. Keep the always-present document-level semantic limit notice. Use conservative known contradiction checks only as supplemental detection; exact-extraction violations remain fatal.
- Report what is checked, not applicable or unavailable. A missing required deterministic check blocks rendering. Limited semantic detection is documented scope, not a fabricated `semantic_truth_passed` check.
- Keep rule failures separate from exceptions and bounded resource-limit failures. If evaluation stops early, report incomplete coverage and do not authorize rendering. Do not rewrite claims, repair citations or invoke a model.

Acceptance: valid references for “contributed” rewritten as “led” never establish truth and fail exact extraction. A known structured responsibility conflict is fatal; suspicious implications from otherwise valid excerpts receive warnings. A deliberately undetected misleading selection fixture still has mandatory semantic review. A source's “may offer hybrid work” cannot become a guaranteed benefit by rewriting; an exact but context-poor excerpt can still mislead. Bounded subjective wording remains proposed, unconfirmed motivation.

Tests: `test_review_warnings.py`, `test_semantic_limits.py`, `test_rule_coverage.py`, `test_safe_diagnostics.py`; include factual disguise, negation, attribution, source qualifiers, warning omission and heuristic false positives/negatives. Configuration impact: stable rule/severity catalog and safe resource limits; no model, cloud service or automatic warning suppression.

### GEN-04-S06 — Persist reports and enforce exact-content rendering gates

**Objective:** Make validation decisions durable and safe to resume before any rendering side effect.  
**Requirements:** R11; supporting R12/R14/R16.  
**Dependencies:** S01–S05, DATA-01, GEN-01, GEN-03 receipt identity; OPS-01 reference inventory.  
**Owned files:** proposed `storage/repositories/document_validations.py`, `generation/validation_store.py`, `validation_adapter.py`, `validation_gate.py`; narrow changes to `storage/migrations.py`, `engine.py`, repository exports, `generation/coordinator.py`/ports and relevant operations inventory hooks.  
**Inputs → outputs:** immutable report → durable receipt/checkpoint and checked render envelope, or explicit blocked/failed state.

Tasks:

- Pin effective rules before evaluation; persist successful and fatal reports atomically with dependency links and content hashes. Maintain one logical report per semantic fingerprint with uniqueness/CAS and separately attributable interrupted attempts. Reuse committed reports; never overwrite audit history.
- Save full report reference/hash and binding in validation checkpoints. Reopen/recompute on resume and immediately before rendering; reject missing, stale, corrupted, cross-request or legacy report authorization. A completed stage Boolean is insufficient, including when an artifact/render checkpoint already exists.
- Repair a missing checkpoint from a committed valid report without regenerating content. A crash before commit may repeat deterministic validation; a crash after commit must reuse the same report. No model invocation or changed input is permitted as recovery.
- Wire versioned rendering input for the GEN-05 boundary. `prepare_render_input` must reopen a trusted stored report, derive the gate and produce detached content plus report/binding refs; a caller-created envelope or capability flag cannot authorize a call. Recheck the draft hash immediately before each output format. Preserve warning refs for downstream review; require artifact approval to remain `draft`. Use fake renderer/deliverer spies until real consumers exist. Update legacy test fakes explicitly; do not keep a permissive production fallback or treat an existing artifact slot as validation evidence.
- Keep errors projected by existing worker plumbing to safe codes/counts/report IDs. Do not concatenate claim text into remote errors. Validator itself makes no remote mutation. Missing dependencies block; deterministic invalidity fails without retry loops; recoverable I/O/capacity errors follow existing bounded policy after remediation.
- Include reports, rule/spec versions and referenced draft/input records in backup/retention/restore checks. Store runtime data outside tracked source; protect reports for failed requests as well as completed ones.

Acceptance: fatal or incomplete report causes zero renderer/deliverer calls. Warnings-only report allows exactly the bound draft to render for review without approval. Editing any title, claim, subjective text, warning or frozen input after validation invalidates the gate. Crash after report commit and before checkpoint recovers the same report with zero inference. Missing/corrupt report on a completed checkpoint blocks rather than silently passing.

Tests: `test_storage.py`, `test_render_gate.py`, `test_coordinator.py`, `test_replay.py`, `test_crash_matrix.py`, `test_retention_restore.py`; real SQLite, fault injection, concurrent identical completions and cross-process reopen. Configuration/migration impact: forward migration after actual head, report tables/reference edges and narrow adapter changes; no Salesforce schema, new processing enum or approval migration.

### GEN-04-S07 — Demonstrate acceptance and hand off to GEN-05

**Objective:** Establish validation guarantees and remaining integration limits with reproducible evidence.  
**Requirements:** R11; supporting R06/R12/R14/R15/R16.  
**Dependencies:** S01–S06; existing GEN-02/03 code for integration and their missing handoffs for owner acceptance evidence; GEN-05 only for later consumer integration.  
**Owned files:** `tests/generation/validation/`, `tests/fixtures/generation/validation/`, optional `tests/manual/gen04_smoke.py`, `config/document-validation.example.json`, relevant README usage and future `docs/components/GEN-04.md`.  
**Inputs → outputs:** synthetic acceptance matrix → recorded checks/results and consumer handoff.

Tasks:

- Exercise CV/cover letter × German/English × JSON/RAG × basic/compact templates. Use real GEN-02/GEN-03 services and SQLite with scripted LLM-01 transport to create receipts; forbid any provider call during validation/replay. Use the same approved source snapshot/purpose semantics; RAG admitted sets may differ. An uncited fact elsewhere in full C01 cannot rescue a claim excluded from the frozen prompt.
- Cover fatal/warning separation, exact reference and protected-value failures, required sections, internal contradictions, misleading-but-bound prose and allowed concurrent roles. Validate injected source instructions cannot disable rules, change severity or invoke tools.
- Run standalone service and worker-adapter scenarios, storage/crash/restore tests and native-Windows paths/restart checks. Keep fixtures wholly synthetic and provider/renderer/projector fakes explicitly labeled.
- Record actual versions, migration number, commands/results and pending gates. Provide GEN-05 success/fatal/warnings-only envelopes, tamper examples, report lookup and warning-retention rules. Report candidate/job citation and issue counts with defined units for future EVAL-01 consumption without building that workflow.

Acceptance: all applicable checks pass at the declared level; the handoff distinguishes unit/contract, real local storage, malformed-input adapter fakes, real GEN-02/03 integration with scripted transport, fake GEN-05 integration and native Windows. The absent GEN-03 handoff remains a prerequisite evidence gap until its owner supplies it; it does not prevent testing the existing code or justify labeling it absent. Do not claim upstream verification, live model quality, downstream rendering, or G4 completion. No live inference or Salesforce access is needed for deterministic validator acceptance.

Tests: `test_integration.py`, `test_windows_paths.py`, `test_windows_restart.py` plus the preceding story suites. Configuration impact: non-secret examples, test-only catalogs and documented production dependencies; no new service/deployment.

## Cross-story acceptance examples

| Synthetic fixture / event | Required observable result |
|---|---|
| Valid P1 candidate fact; P2 now current | Resolve P1 bytes and permissions only; no latest-profile read. |
| Candidate claim cites a job requirement or job claim cites candidate history | Fatal subject/reference mismatch, regardless of matching words. |
| Correct fact UUID with unrelated metric; valid J1 revision with false quote | Fatal metric/reference finding with safe location; zero rendering calls. |
| J1 text contains umlauts/emoji; span computed in UTF-16 units or outside string | Reject incorrect code-point range/quote match; exact Unicode fixture passes. |
| Year-only start date rendered as a precise month; null end rendered as ongoing | Fatal invented precision/unsupported ongoing assertion. |
| Exact original titles/metrics; factual translation added to C14 | Original-language text passes equality; rewritten factual text or extra display fields fail the current recipe/schema. Source-language review remains mandatory. |
| Same metric value, changed beneficiary, denominator or accomplishment | Fatal where structured mismatch is demonstrable; semantic-warning/limit coverage otherwise, never a truth certification. |
| Required section missing but other sections valid | Fatal; no partial render or fabricated filler. |
| Two supported roles overlap; dates are only year precision | Warning/uncertain order, not an automatic employment contradiction. |
| Valid exact excerpt selected/grouped misleadingly beyond heuristic detection | Report still states semantic limits and mandatory human review. Test does not assert complete detection. |
| Model drops availability/source warning or labels factual header subjective | Inherited warning remains; detected unbound factual assertion is fatal. |
| Frozen body changes but stored digest labels do not | Recomputed integrity check blocks validation/replay. |
| Validation report says allowed but hash belongs to another draft/request | Gate rejects; no renderer or delivery call. |
| All deterministic checks pass, with or without warnings | Exact draft can render for review only; approval stays `draft`, no validation-driven readiness notification. |
| Rules/config change between attempts | Original pinned rules replay; deliberate upgrade makes a distinct report requiring fresh gate checks. |

## Configuration, migration and verification impact

| Area | Planned impact |
|---|---|
| Rule configuration | Proposed `DocumentValidationSettings` with versioned rule catalog, supported schema/spec references and bounded input/report limits. Pin effective configuration/digest at first validation. No `skip_validation`, `auto_approve`, fatal-to-warning overrides or warning-to-approval thresholds. Unknown options fail visibly. |
| Content requirements | Consume the sealed GEN-03 allowed-heading spec and bind the explicit supplemental GEN-04 required-content policy by recipe/template/type/version/digest. Missing mapping is a dependency failure. Pin this policy at first validation; do not rewrite the upstream seal or alter user language/template/strategy selection. |
| Shared contracts | New versioned report/gate schemas and explicit legacy compatibility. C14 v2 remains GEN-03 ownership; C01 ongoing/identity gaps remain upstream. Any necessary incompatible shared change requires blueprint decision, fixtures and consumer migration. |
| Storage | Forward-only migration after implementation-time head; preserve old checkpoints as inspectable, untrusted for new authorization. Immutable report/run records and dependency refs; no artifact files created by GEN-04. |
| Paths/privacy | Reuse configured absolute Windows data root, `pathlib.Path`, explicit config/package bases and safe metadata-only diagnostics. Do not follow job-supplied paths or put candidate/source text into logs, Git, public handoffs or remote error fields. |
| Dependencies | Existing Python/Pydantic/SQLite stack; no model inference, network dependency, paid API, mandatory Word, LibreOffice installation, scheduler or UI. |

Implementation-time commands below are **planned, not executed by this documentation task**. Add affected configuration/CLI/schema tests when those files change, then run the repository regression gate. Record actual exit codes and environment rather than reusing prior handoff results.

```powershell
$gen04Repo = (Resolve-Path '.').Path
$gen04Python = Join-Path $gen04Repo '.venv\Scripts\python.exe'
& $gen04Python -m pytest (Join-Path $gen04Repo 'tests\generation\validation')
if ($LASTEXITCODE -ne 0) { throw 'GEN-04 component checks failed' }
& $gen04Python -m pytest (Join-Path $gen04Repo 'tests\generation') (Join-Path $gen04Repo 'tests\profile') (Join-Path $gen04Repo 'tests\contracts') (Join-Path $gen04Repo 'tests\storage') (Join-Path $gen04Repo 'tests\operations')
if ($LASTEXITCODE -ne 0) { throw 'Affected integration checks failed' }
$gen04Temp = Join-Path $env:TEMP ('GEN-04 Prüfung ä ' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $gen04Temp | Out-Null
Push-Location -LiteralPath $gen04Temp
try {
    & $gen04Python -m pytest (Join-Path $gen04Repo 'tests\generation\validation\test_windows_paths.py') (Join-Path $gen04Repo 'tests\generation\validation\test_windows_restart.py') --basetemp (Join-Path $gen04Temp 'Daten Größe')
    if ($LASTEXITCODE -ne 0) { throw 'Windows path/restart checks failed' }
} finally {
    Pop-Location
}
& $gen04Python -m pytest (Join-Path $gen04Repo 'tests')
if ($LASTEXITCODE -ne 0) { throw 'Regression checks failed' }
```

The Windows fixtures must exercise a real subprocess reopening saved reports after termination, paths with spaces/umlauts, another working directory, locked/unwritable storage, and a fresh restore into a separate data root. A populated migration-012 database must retain prior drafts, attempts, audits and checkpoints; repeated migration must be idempotent and retain historical migration checksums. Inject failures before/after report commit and checkpoint commit, and between DOCX/PDF requests. Report actual Python/PowerShell/OS versions and safe exit results. Do not clean or overwrite an existing user data directory. These are future implementation checks, not results of this planning task.

## Implementation handoff checklist

- [ ] State GEN-04 status and R11 acceptance; list owned/changed files and exact dependency/schema/interface/migration versions.
- [ ] Obtain the missing GEN-03 handoff or retain the prerequisite acceptance-evidence gap explicitly; record GEN-02 code versus acceptance status.
- [ ] Record real upstream-code integration separately from missing owner handoff/verification evidence; document exact extraction, whole-list protected values, material-hash citations and supplemental required-section policy.
- [ ] Demonstrate frozen candidate/job source separation, approval/purpose/admitted-ID enforcement, exact quotation/span matching and nested-body integrity checks.
- [ ] Demonstrate date precision/null/ongoing handling, source-backed titles/metrics, required sections and consistency rules with both fatal and warning examples.
- [ ] Record C01 string-metric/ongoing/identity limitations without inventing upstream facts or silent schema changes.
- [ ] Explain misleading-paraphrase detection limits, known false positives/negatives and the mandatory human-review obligation even with no localized warnings.
- [ ] Publish report/gate schemas, rules/spec digests, legacy behavior, safe diagnostic codes and readable consumer examples.
- [ ] Prove fatal/incomplete/stale results prevent rendering; warning-only results retain warnings and never approve content or independently mark readiness.
- [ ] Prove report/checkpoint crash recovery, exact-content reuse, rule-version invalidation and protected backup/restore dependencies.
- [ ] Separate unit/contract, fake integration, real local persistence, real GEN-03 integration and native-Windows verification; identify pending downstream GEN-05/06 work.
- [ ] Leave rendering, delivery, human approval, notifications and Phase 2 with their owning components.

Planning result: **all seven stories remain PLANNED**. This task updates only `docs/stories/GEN-04.md`; it implements no application code, schemas, configuration, migrations or component handoff and runs no application verification suite. The requested GEN-03 handoff could not be read because it is absent; the blueprint decision and existing GEN-03 code/tests were inspected instead, without inventing verification results.
