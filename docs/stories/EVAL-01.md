# EVAL-01 — Evaluation and feedback

Status: **PLANNED — implementation stories only**  
Date: **29 October 2026**  
Scope: **EVAL-01 only; Phase 0 with explicitly deferred Phase 1 extensions**  
Primary requirement: **R13**; supporting constraints: **R05/R06/R07/R09/R14/R15/R16**, and **R11/R12** for Phase 1.  
Catalog dependencies: **MATCH-01, MATCH-02, CONTEXT-04, RUN-01**; generation components for Phase 1.

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§2–5 (requirements, contracts, authority), §6 EVAL-01, §7 G2/G4, and §§8–10 (handoffs, Windows and ownership). Repository guidance: [README](../../README.md) and [schema generation instructions](../../schemas/README.md). No applicable `AGENTS.md` was found in checked ancestors or repository directories; the user-level `.codex/AGENTS.md` was empty.

EVAL owns labeled fixtures, reviewer corrections, rejected-job sampling, local comparison execution and metrics. It consumes the existing rule evaluator, assessor, context selector and local model provider. It does not change candidate truth, production policy, assessment prompts, retrieval algorithms, model selection, publication selection or Salesforce state. Findings can recommend owner changes; applying those changes requires a new version and a separate experiment. This document creates no code, schemas, fixtures, measurements or external writes.

## Current repository evidence and dependency gates

Paths in this document use `/` as documentation notation. Implementation must recheck current code and versions before starting; recorded test counts below are historical handoff evidence, not tests run by this planning task.

| Dependency / inspected evidence | Consequence for EVAL |
|---|---|
| [MATCH-01 handoff](../components/MATCH-01.md); `assessment/{service,inputs,deterministic_trace,composition}.py` | Handoff says VERIFIED and records 50 assessment checks on native Windows. Use fully bound `AssessmentService.evaluate_posting_with_trace(...)` or `evaluate_deterministic_with_trace(AssessmentInput)`. Preserve exclusions, eligibility and missing-policy rejections in addition to `rule_outcomes`. Do not use the legacy synthetic-posting fallback. |
| [MATCH-02 handoff](../components/MATCH-02.md); `assessment/{llm_service,llm_records,llm_inputs,llm_inference,llm_prompts,context_bridge}.py` | `LLMAssessmentService.assess(AssessmentRequest)` returns success with C11 or pending without C11. Set `assessment_mode=COMPARISON` explicitly: the default is PRIMARY. Handoff reports 106 targeted checks and a local smoke, but overall live verification remains pending. These establish neither corpus quality nor a chosen production model. Actual request defaults differ from handoff examples; freeze explicit settings. |
| [CONTEXT-04 handoff](../components/CONTEXT-04.md); `context/{selector,selector_records,preparation,rag_builder,retrieval_settings}.py` | Real selector returns C09, rendered prompt and optional `RetrievalTrace`; JSON has no retrieval trace. RAG distinguishes raw hits, fused candidates, mandatory IDs and budget omissions. Historical evidence uses fake embeddings; live retrieval/benchmark acceptance is pending. Defaults such as `top_k=8` and `rrf_k=60` are engineering settings, not measured quality targets. |
| [RUN-01 stories](RUN-01.md) | **No `docs/components/RUN-01.md` handoff or `orchestration/` implementation exists at inspection.** Consume its proposed frozen input/selection/lock/report boundaries only after they exist. DG3 (exact C06/revision binding), DG5 (model identity and actual prompt admission), S06/S09 (selected results) and S10 (verification) are relevant gates. Do not report RUN integration as complete using an EVAL replacement runner. |
| `storage/repositories/assessments.py`; `salesforce/{sync_service,sync_records}.py` | `get_latest_assessment()` does not filter comparison records. Tracked refresh currently reads that latest assessment. Although SYNC rejects non-primary publication purposes, writing evaluation C11 into the production assessments table could affect later refresh. Separate evaluation persistence is mandatory; a comparison flag alone is insufficient. |
| `models/{provider,audit,inputs}.py`; current assessment/context integration tests | Provider audit hooks and a shared input resolver exist. Audit references in MATCH-02 success are not the full requirement set, C09, trace, proposal or final transport payload. Failed attempts also require capture. Reuse real services with scripted transports for offline checks. |
| `configuration.py`, `cli.py`, `schemas/README.md`, package tree | Native paths and loopback model restrictions exist. No `evaluation/` or `generation/` implementation exists. Shared schemas are generated from typed models, never edited by hand. Use additive evaluation companion records rather than redefining C01–C15. |

Concrete gates, owned by the indicated components:

| Gate | Evidence needed | Work that can proceed while pending |
|---|---|---|
| **EG1 — exact frozen inputs (RUN/DATA/IDENTITY)** | Read-only export of selected C11 plus exact C06, canonical/revision UUID and material hash, C01/C02 and full deterministic trace. A revision cannot resolve to today's source-key row. | Synthetic fixture and metric work; real rejected-job sampling remains pending if bindings cannot be proven. |
| **EG2 — comparable model execution (MATCH/CONTEXT/LLM)** | Full input manifest; identical prepared requirements in each pair; actual effective model digest/settings; complete transmitted prompt budget and identity. `context_bridge.py` currently receives empty instruction/schema defaults while `llm_inference.py` rebuilds system/user framing afterward. Prove admission of that final payload; C09 budgeting alone is insufficient. | Contract tests and explicit diagnostic runs. Do not label runs controlled comparisons when this gate fails. |
| **EG3 — observable evidence (MATCH/CONTEXT/LLM)** | Read-only capture of requirement preparation, C09/trace, model proposal/result, validation findings, C11 and failures with correlated IDs. Existing selector/provider decorators may capture data without changing behavior; any missing hook belongs to its owner. | Synthetic attribution oracles. Missing observations are `unavailable`, never inferred from final citations. |
| **EG4 — RUN integration and isolation (RUN/SYNC)** | Implemented read-only export and shared model-worker locking; comparison paths have no primary-selection token, outbox route, drain/recovery route or credential access. | Standalone isolated fixture comparisons; keep overall catalog integration pending. |
| **EG5 — live execution (MODEL-01/02)** | Available explicitly configured local generation and embedding models, verified immutable identities, actual hardware/runtime metadata and measured configuration. | Offline fake-transport checks, clearly labeled; no invented live performance claims. |

Only narrow, owner-agreed observability/admission changes may be prerequisites to EVAL. EVAL must not copy the assessor, extractor, renderer, selector or RUN orchestration to bypass an unmet gate.

## Experiment and measurement contract

The following record names, file layout and CLI are **proposed engineering choices**, to freeze in S01. The user's requirements are the scope, controlled comparison, separate attribution, rejected review, no publication and deferred document extensions. No numeric quality threshold or corpus size has been user-approved.

### Controlled pairs

Each experiment has a UUID and immutable manifest. Each case/repetition has one pair ID, separate JSON/RAG arm IDs and stable logical work IDs; attempts retain their own IDs. Freeze these shared controls by version **and content hash**:

- Exact C01 snapshot, approval and candidate ID, permitted evidence universe, inclusion rules, mandatory policy, explicit eligibility and chronology. Later revocation blocks execution; freezing is not permission to ignore revocation.
- Exact C06/C07 binding and source provenance; effective C02 including aliases, thresholds and missing behavior; MATCH-01 version, baseline and full trace.
- Requirement extractor mode, implementation and prompt versions, prepared requirement set and source spans. Initial controlled lane uses deterministic extraction and verifies identical outputs in both arms. An LLM extractor needs an owner-supported prepare-once/replay boundary; until then it is an explicitly confounded diagnostic lane, not the primary comparison. Gold labels never become extraction input.
- Generation model identifier and immutable digest, runtime/provider version, actual effective decoding settings (including seed where supported), assessment prompt version **and template bytes**, schema, tokenizer/estimator, chat framing, context window, output reserve and safety allowance. Pin software revision and relevant dependency versions. A mutable model tag or equal version strings with different bytes cannot establish equality.
- Corpus/label revision, split, metric specification, sampling plan, repeat count and arm order. Serialize inference; counterbalance JSON-first/RAG-first with a recorded seed. Treat repeated calls as repeated observations of one case, not independent jobs.

Only context strategy and its documented context output differ within a pair. Record RAG-specific chunk/index generation, embedding digest/dimensions/prefixes, query/retrieval settings and builder/serialization versions; JSON has explicit `not_applicable` values. Full JSON retains all permitted facts or reports overflow. Never truncate JSON, switch strategies, change budget/model/prompt between arms or choose the best retry. Provider nondeterminism can remain despite a seed; report observed variability.

Changing retrieval settings or assessment thresholds creates a new experiment on the development split. Freeze the selected configuration before a held-out run. Never tune on the held-out result and continue calling it untouched validation. Changed profile facts/model/prompts require a new experiment family; any cross-family result is not a strategy-only attribution.

### Evidence stages and metric definitions

Gold annotations belong to human-reviewed requirements and evidence, independently of the extractor's predicted IDs. Store source spans and an explicit predicted-to-gold alignment. Alternative sufficient evidence sets are allowed, including multi-fact support; citing any one fact is not sufficient when the label requires several. Keep documented contradiction, not documented, restricted evidence and unresolved annotation distinct.

For requirement `r`, let `G_r` be its eligible gold fact IDs, `H_r` raw retrieved fact IDs, `K_r` optional candidates surviving ranking/top-k, `A` actually admitted C09 facts, and `U_r` final C11 cited facts for that requirement. Deduplicate facts across chunks/queries. Preserve separate mandatory/ancestor origin labels. C08 references to structured eligibility/job fields need their own resolvable coverage records and must not be fabricated as candidate fact UUIDs.

| Measure | Definition / attribution |
|---|---|
| Requirement extraction | Reviewer-aligned precision/recall, obligation/negation/alternative errors and unsupported extractions. Missed extraction is an upstream failure, not automatically a retrieval miss. |
| Retrieval coverage | `|G_r ∩ H_r| / |G_r|` before ranking, plus `|G_r ∩ K_r| / |G_r|` after ranking. Score optional retrieval separately from mandatory facts; mandatory bypass must not inflate retrieval recall. Report keyword/semantic channels separately where trace supports them. JSON retrieval metrics are N/A. |
| Admitted evidence coverage | `|G_r ∩ A| / |G_r|`, plus whether any complete sufficient evidence set was admitted. Separate rank/top-k loss from retrieved-but-budget-omitted and permission/parent restrictions. JSON admission is measured, not assumed. |
| Final evidence use | Citation use `|G_r ∩ A ∩ U_r| / |G_r ∩ A|`, plus reviewer-confirmed sufficient semantic support. Citation validity alone is not correct evidence use. Report available-but-unused, cited-but-misinterpreted and unadmitted/invalid citation separately. |
| End-to-end support | Requirements with reviewer-confirmed correct, sufficiently supported findings / adjudicated evaluable requirements. Preserve attribution to extraction, retrieval, packing, inference or composition; do not force every failure into retrieval. |
| Matching errors | Full eligible/review/rejected confusion matrix on completed adjudicated cases, plus per-rule and requirement-status errors. For retention, gold eligible or review is positive: FN = predicted rejected among these; FNR = FN / all gold positives with completed predictions. Report gold-eligible-only FNR separately. Precision for predicted eligible = gold eligible / all predicted eligible. False positives and review burden have their own counts. |
| Rejected-sample error | Gold eligible/review among reviewed system rejects / all adjudicated sampled rejects. Call this the **false-omission proportion among rejects**, not population FNR; a reject-only sample has no denominator for all missed relevant jobs. Report policy-driven missing-data rejection separately from factual shortfall. |
| Unsupported claims | Unsupported factual claims / adjudicated factual claims in proposal and final output separately, plus affected cases. Include summary prose, not just typed findings. Valid IDs with exaggerated meaning still count as unsupported. Unreviewed claims remain unknown. |
| Effort and latency | Active reviewer time, changed decisions/findings, correction count and review completion; monotonic elapsed times for extraction, query embedding, selection/packing, inference/validation and whole case. Report retries/queue waits separately, cold/warm conditions and model-reported usage versus measured/estimated tokens. Index build time is separate from per-query latency. |

Zero denominators produce `null`/N/A with counts, not perfect scores. Missing traces produce unavailable metrics, not zero retrieval. Pending calls, invalid model outputs, missing configuration, context overflow and audit failure remain visible execution outcomes; they never enter the confusion matrix as rejected jobs. Show all attempted-case counts and arm-specific completion rates alongside matched-complete pair metrics so dropping failed arms cannot make a strategy look better.

Report micro totals and per-case macro results with denominators, strategy deltas on the same completed pairs, strata, repetitions and uncertainty/sample limitations. Where intervals are implemented, record their method and resample at canonical-job group level. Do not generalize a synthetic corpus or purposive sample to the German job market. Scores are ranking signals, not offer probabilities.

## Ordered implementation stories

All stories belong only to **EVAL-01**. S01–S08 are **PLANNED / Phase 0**; S09–S10 are **DEFERRED / Phase 1**. Paths starting `evaluation/` are relative to `src/job_automation/`. Shared-file edits are narrow integration changes, not ownership transfer.

### EVAL-01-S01 — Freeze evaluation records, controls and metric specification

**Objective / requirement and contract references.** Establish auditable experiment identities before executing comparisons. R13 with R06/R07/R15/R16; C01/C02/C06–C11 and negative C12 boundary; blueprint §§4–5 and the experiment contract above.

**Dependencies.** Current MATCH-01/02, CONTEXT-04, FND-01/DATA-01 contracts; RUN-01 planned bindings and EG1–EG3. No live service required for record design.

**Inputs → outputs.** Existing contract instances and the experiment/metric rules → versioned `EvaluationCase`, `GoldLabelRevision`, `ExperimentManifest`, `PairResult`, `ArmAttempt`, `ReviewCorrection`, `SampleManifest` and `MetricReport` companion records, with strict validators and a dependency-gate register.

**Owned files.** Proposed `evaluation/{__init__,records,settings,ports,errors,fingerprints}.py`, `tests/evaluation/test_contracts.py`, `tests/fixtures/evaluation/README.md`. Narrow `contracts/export_schemas.py` registration and generated evaluation schemas only if shared export is selected.

**Tasks.** Specify permitted-input versus label separation, identity/hash rules, comparison-only authority, pending/invalid/incomplete-pair states, stage attribution, units and denominator rules. Freeze the case/pair/repetition keys and complete input manifest. Define separate execution outcome and measured quality outcome. Agree owner hooks for EG1–EG3 and version incompatible changes explicitly.

**Acceptance criteria.** Equal labels or version strings cannot hide changed input bytes. A mixed-profile/model/prompt pair fails validation before execution. A pending envelope cannot be a completed C11. Gold labels and reviewer expectations are inaccessible through the model-input port. Comparison records cannot request primary publication.

**Tests.** Serialization/schema parity; malformed references, unknown versions, hash tampering, mismatched arms and zero-denominator examples; identical semantic manifests hash identically despite attempt timestamps. Include same-version/different-content conflicts.

**Configuration / migration impact.** Versioned EVAL settings are separate from production policy. No production schema migration planned; document any generated companion schemas and consumer compatibility. Model IDs, sample sizes and thresholds remain explicit choices.

### EVAL-01-S02 — Build a labeled matching and evidence corpus

**Objective / requirement and contract references.** Supply independent expected outcomes and evidence for both strategies. R13/R05/R06/R15; C01/C02/C06/C07/C08/C11; blueprint §5 unknowns, hard-rule precedence and evidence semantics.

**Dependencies.** S01; MATCH-01/02 and CONTEXT-04 fixture catalogs; PROFILE-01/POLICY-01 inclusion and approval rules. EG1 for imported real cases.

**Inputs → outputs.** Synthetic approved profiles, exact postings/policies and reviewer annotations → versioned corpus manifests, independently justified labels, development/held-out splits and provenance records.

**Owned files.** `evaluation/{corpus,labels,split}.py`; `tests/fixtures/evaluation/{matching,evidence,profiles,policies}/`; `tests/evaluation/{test_corpus,test_labels,test_split}.py`; fixture README.

**Tasks.** Create stable case/requirement IDs, source-span labels, rule expectations, final disposition, sufficient evidence alternatives, evidence contradictions/unknowns and annotation status/reviewer/rationale. Include broad white-collar roles, German/English adverts, semantic aliases without exact keywords, C++/C#/.NET, hard failures, preferred/required distinctions, negation/alternatives, missing salary/authorization, remote restrictions, advert-language versus fluency, low scores, no documented evidence, restricted parents, mandatory chronology, top-k misses, budget omissions and hostile instructions. Include correctly cited but inflated claims. Adapt existing tests as mechanics examples, not independent quality labels.

Group alternate sources/revisions of the same canonical opportunity and near-duplicate adverts into one split to prevent leakage. Keep held-out labels unavailable to tuning/model inputs. Real candidate/job data and annotations stay in a protected external corpus; commit only synthetic non-sensitive fixtures. Never invent candidate approval or import private data merely to increase corpus size.

**Acceptance criteria.** Every scored expectation has evidence and an adjudication state. Missing skill documentation is unknown, not confirmed inability. Restricted facts cannot be gold for an assessment-purpose retrieval score. Duplicate opportunity variants never cross splits. A representative category checklist is explicit; no fabricated claim of statistical representativeness or minimum sample achievement.

**Tests.** Invalid spans/versions, disallowed gold facts, orphan parents, duplicate IDs, split leakage and missing approval fail. Hand-labeled examples cover alternative sufficient sets and full multi-fact support. Withheld labels never occur in captured requests/prompts.

**Configuration / migration impact.** Corpus root/version, split seed and grouping algorithm are explicit manifest fields. No source acquisition or policy changes. Real data paths resolve against the configured base, outside the checkout.

### EVAL-01-S03 — Persist isolated evaluation work and enforce no publication

**Objective / requirement and contract references.** Make accidental Salesforce publication impossible through evaluation composition and prevent later production consumption. R13/R09/R15/R16; C11/C12/C15 and blueprint §§3/5 comparison authority.

**Dependencies.** S01; DATA-01 patterns; RUN-01 lock/export integration when available (EG4). Inspect SYNC-01's comparison guard as defense in depth, not as EVAL's execution path.

**Inputs → outputs.** Frozen cases/configuration and attempts → EVAL-only database/artifacts, resumable local work and safe reports; **zero production selection, C12 or Salesforce effects**.

**Owned files.** `evaluation/{repository,migrations,workspace,composition,recovery}.py`; `tests/evaluation/{test_isolation,test_no_publication,test_recovery,test_paths}.py`.

**Tasks.** Use a dedicated EVAL database with its own migration ledger and protected artifact root, physically distinct from production storage. Import only consistent read-only exports; do not migrate/open production repositories for writes. Store C11-shaped payloads in EVAL tables, never production `assessments`. Reject database/root aliasing, including supported Windows case/junction aliases. Construct no Salesforce gateway, credential resolver, sync service, selection registration, outbox dispatcher, candidate backup, notification or source-fetch component. There is no `--publish` override. Reject publication configuration rather than treating it as a harmless dry-run setting.

Persist manifest, arm attempts, outputs and receipts atomically where local; no transaction spans model calls. Resume only verified outputs with matching manifests and permissions. Partial pairs remain partial; audit failures remain visible. Reuse RUN's model-worker ownership once available; until then fixture harnesses must have explicit isolation and cannot claim shared-worker acceptance. Do not implement search recovery in EVAL.

**Acceptance criteria.** Completed, failed and resumed comparisons leave production assessment/selection/outbox rows and candidate state unchanged, even with credentials present and old pending production writes. A newer comparison cannot become `get_latest_assessment()` for production. Starting EVAL cannot drain existing work. Same logical arm is not duplicated after result commit/restart.

**Tests.** Sentinel production DB with tracked and untracked jobs, primary selection and pending outbox; compare before/after logical rows and assert zero credential/gateway/dispatcher calls. Try malicious publication flags, root aliases, input DB path confusion, failure recovery and shutdown. Kill between artifact save and receipt; verify recovery or explicit repair. No real Salesforce credentials/network are needed.

**Configuration / migration impact.** EVAL-only storage migrations; no production migration. Require explicit evaluation root and read-only input references; finite retry/attempt limits. Preserve existing local model loopback restrictions and protect raw evaluation artifacts from ordinary logs/source control.

### EVAL-01-S04 — Execute frozen JSON/RAG assessment pairs

**Objective / requirement and contract references.** Compare context strategies with facts, model and assessment prompt held constant. R13/R05/R06/R07; C01/C02/C06–C11; assessor, selector and provider boundaries.

**Dependencies.** S01–S03; MATCH-01/02, CONTEXT-01–04, LLM-01; EG2/EG3 for controlled acceptance, EG5 for live evidence, EG4 for shared execution integration.

**Inputs → outputs.** Frozen manifest, corpus cases, approved snapshot, explicit local model and compatible index → rules baseline plus JSON/RAG arm results, captured intermediate records, timed attempts and comparison-validity decisions.

**Owned files.** `evaluation/{runner,assessment_adapter,capture,manifest_validation,timing}.py`; `tests/evaluation/{test_pairs,test_capture,test_input_controls,test_pair_failures}.py`. Any missing upstream audit or prepared-requirement hook is an owner gate, not a second implementation here.

**Tasks.** Build the deterministic baseline once per frozen case. Bind real `LLMAssessmentService`, shared selector, provider and the same input resolver. Set comparison mode explicitly. Capture selector request requirements and verify pair identity; for the initial deterministic lane compare canonical requirement outputs as well. Capture C09, raw/fused/admitted traces, final model payload identity, C10 proposal/result, validation issues and C11 without changing requests. Verify effective provider settings/digest and final prompt admission, not just requested values. Persist failed-stage data where available.

Run arms serially in counterbalanced order. Ordinary production routing skips model work for deterministic rejects; mark those rules-only cases separately. A declared diagnostic cohort may call both arms on such cases to test hard-fail preservation, with separate costs and no publication. Explicit repetitions measure stochastic variation; retries follow failure policy and never select the highest score. Reuse only identical committed work and retain original timing; cached observations are not new latency samples.

**Acceptance criteria.** Profile/model/prompt drift blocks the pair; strategy is the only treatment change. A hard failure survives score 100. JSON overflow or RAG index mismatch yields a visible failed/pending arm without fallback. The admitted prompt and transmitted framing pass EG2; if not, results are diagnostic/uncontrolled and excluded from strategy-only claims. Labels are never transmitted. Both arm results remain independently inspectable.

**Tests.** Real assessment/context components with scripted transport and fixture indexes; deliberate model-tag change, altered prompt bytes, effective-setting drift, different requirements, wrong revision and post-selection prompt growth. Outage, schema error, invalid citation, one-arm completion, retry and restart. Assert actual call counts and captured identities. Live tests are opt-in and separately recorded.

**Configuration / migration impact.** Explicit model/digest, limits, extractor mode, repetition/order seed, retrieval/index/embedding references and finite timeouts. No fallback model or production strategy changes. New experiment IDs for any changed control or treatment setting.

### EVAL-01-S05 — Attribute errors and produce honest comparison metrics

**Objective / requirement and contract references.** Separate retrieval coverage, admitted context and final evidence use; quantify matching errors, unsupported claims and latency. R13/R05/R06/R07; C08–C11 and the metric definitions above.

**Dependencies.** S01/S02/S04; EG3 observations; human semantic adjudication from S06 for reviewed metrics. Unreviewed automated traceability reports can precede S06, clearly labeled.

**Inputs → outputs.** Frozen gold labels, captured stages, timings and review records → versioned machine-readable metrics and readable comparison report with per-case attribution and drill-down IDs.

**Owned files.** `evaluation/{metrics,attribution,reporting}.py`; `tests/evaluation/{test_metrics,test_attribution,test_reporting}.py`; synthetic metric-oracle fixtures.

**Tasks.** Implement the metric table with explicit denominators, valid-pair filters, completion/error rates, micro/macro summaries and strata. Align extracted requirements to gold without erasing unmatched gold requirements. Track optional retrieval separately from mandatory/ancestor admission. Preserve raw proposal claims versus validated final claims; final citations show observable evidence use, not hidden model reasoning. Report raw/final validation issues and reviewer semantic judgments separately. Where ranking/top-k information is not exposed reliably, mark it unavailable and request an owner hook instead of inferring it from final selection.

Report stage latency and token measurement provenance, paired deltas, cold/warm conditions and repetitions. Publish proposed targets in a separate field/table from observations. Threshold recommendations include corpus/split/version, sample size, uncertainty and tradeoffs; they do not rewrite production configuration.

**Acceptance criteria.** A gold fact absent from hits is retrieval loss; a hit omitted for budget is packing loss; admitted evidence unused is inference-use loss; valid citation with exaggerated meaning is semantic misuse. No-documented-evidence is not retrieval failure. JSON retrieval is N/A. Incomplete arms and unreviewed claims cannot disappear from totals. Review is not silently treated as either eligible or rejected.

**Tests.** Hand-calculated counts for confusion matrices, alternative evidence sets, repeated chunks, mandatory-only cases, retrieval/ranking/budget losses and cited-but-wrong claims. Zero denominators, all-pending runs, one-arm failure, missing trace, partial review, duplicate repetitions and report regeneration must retain correct units/counts. Verify reject-only false-omission rate is never labeled FNR.

**Configuration / migration impact.** Version the metric specification and optional target registry. No default production quality threshold or new paid analytics dependency; standard-library calculations are sufficient initially. Re-scoring creates a new report revision referencing unchanged raw observations.

### EVAL-01-S06 — Capture reviewer corrections without changing candidate truth

**Objective / requirement and contract references.** Turn review into auditable labels and measurable effort. R13/R15/R16; C01/C02/C08/C11; blueprint §5 authority and human judgment.

**Dependencies.** S01–S03; S04 outputs; S05 report semantics. PROFILE-01/POLICY-01 remain owners of fact/policy edits.

**Inputs → outputs.** Case packet, original labels, predictions and cited sources → append-only `ReviewCorrection` events, adjudicated label revisions, disagreement records, reviewer-effort observations and owner-directed change proposals.

**Owned files.** `evaluation/{review,review_import,review_export}.py`; `tests/evaluation/{test_review,test_corrections,test_review_privacy}.py`; synthetic review templates. Use local CLI/JSON review packets; no new dashboard or Salesforce workflow.

**Tasks.** Separate initial labeling from prediction review; hide strategy/model labels and randomize arm display where practical, recording when blinding is impossible. Capture reviewer identity, UTC time, case/arm/output hashes, old/new value, reason, supporting C08 references, correction category, uncertainty/adjudication state and active review duration. Categories include extraction, policy/rule, retrieval, budget, missing use, unsupported/inflated claim and annotation error. Allow disagreement and unresolved cases; do not manufacture a second reviewer.

Preserve original prediction and label versions. Corrections revise evaluation labels only after explicit adjudication. A proposed new candidate fact requires PROFILE-01 approval in a future snapshot; preference changes require POLICY-01. Neither enters the active pair or updates candidate-owned Salesforce decisions. Review-time pauses/missing timers are explicit; elapsed idle time is not editing effort.

**Acceptance criteria.** Re-importing the same correction is idempotent; conflicting edits require resolution. Old reports remain reproducible against old labels. Corrected reports cite the new label version without rerunning models silently. Review does not mutate production facts, policies, selected assessments or remote notes. Unreviewed is distinct from accepted without edits.

**Tests.** Duplicate/colliding events, stale output hash, invalid evidence, wrong profile revision, incomplete review and disagreement. Attempt a profile/policy write through correction import and assert rejection. Check report revision reproducibility and active-time aggregation.

**Configuration / migration impact.** Review format/rubric version, local reviewer identifier and optional time capture. Append-only EVAL records; no production schema change. Protected review packets can contain sensitive data and must not enter source control or ordinary diagnostics.

### EVAL-01-S07 — Sample locally rejected jobs and audit false omissions

**Objective / requirement and contract references.** Find missed opportunities beyond visible positive results and distinguish factual rejection from policy/keyword errors. R13/R05/R09; C02/C06/C07/C11 and selected RUN input bindings; blueprint §5 rejected-job sampling.

**Dependencies.** S01–S03/S06; MATCH-01 trace; RUN-01 selected-result export and EG1/EG4 for real samples. Synthetic exports can verify mechanics while RUN remains pending.

**Inputs → outputs.** Frozen local assessment population for a declared run/date/input cohort → reproducible sample manifest, local review packets and stratum-level reviewed outcomes; optional new controlled experiments through S04.

**Owned files.** `evaluation/{sampling,population_reader,sample_review}.py`; `tests/evaluation/{test_sampling,test_population_binding,test_sample_metrics}.py`.

**Tasks.** Select production-final assessments through explicit selection references, never the latest row. Include locally retained, never-published rejects and distinguish already-tracked rejects. Freeze one evaluation unit per canonical job/cohort with exact revision/profile/policy and source provenance; avoid duplicate weighting for alternate boards. Exclude comparison records, candidate application-status Rejected, availability-only closure and pending inference from the system-reject population, recording counts/reasons.

Stratify by rejection reason (hard factual failure, explicit exclusion, missing-policy fail, semantic required gap, and any actual keyword/relevance rejection), source shape, language and role; retain multi-reason tags but choose a deterministic non-overlapping primary stratum for weighting. Do not invent a score-based rejection stratum when current MATCH-02 routes low score to review. Use seeded sampling without replacement, record population/sample sizes, inclusion probability, frame hash and selected IDs. Small strata can use a census. Separate deliberately chosen hard cases from probability samples.

Review sampled rejects against their frozen facts and policy; optionally collect an eligible/review control sample for broader matching metrics. Record unreviewed and unavailable-history cases, never silently replace them. A policy preference disagreement is distinct from an evaluator defect. Rerun corrected facts/settings only as a new experiment, leaving historical rejection untouched.

**Acceptance criteria.** Same frame/seed yields the same sample regardless of row order. Never-published rejects are reachable without Salesforce. No sampling operation reassesses/selects/publishes production jobs. Report reject false-omission proportions, stratum denominators and review coverage; use population weighting only where inclusion probabilities and response coverage justify it. Reject-only samples never claim overall recall/FNR. Empty frames are explicit empty results.

**Tests.** Shuffled input, duplicate sources/revisions, multiple reasons, insufficient stratum size, empty frame, changed frame hash, missing exact history, later comparison row and stale selection. Seed reproducibility, correct probabilities/weights and nonresponse counts. Assert zero production writes during sampling and re-review.

**Configuration / migration impact.** Explicit cohort filters, seed, per-stratum counts/fractions and review budget, frozen before labels are observed. No automatic scheduler, policy threshold changes or acquisition adapter. RUN export remains a pending integration gate until implemented.

### EVAL-01-S08 — Expose local commands, verify Windows behavior and publish the handoff

**Objective / requirement and contract references.** Make controlled evaluation repeatable with honest verification and completion status. R13/R14/R15/R16; C09–C11, C15 read-only references where applicable; blueprint §§7–9.

**Dependencies.** S01–S07; EG1–EG4 for production-input/RUN integration, EG5 for live measurements. Offline component checks do not require Salesforce or generation components.

**Inputs → outputs.** Validated configuration, corpus, samples and artifacts → proposed `evaluation check|run|resume|report|sample-rejects|review-export|review-import` CLI, offline/native/live evidence and `docs/components/EVAL-01.md`.

**Owned files.** `evaluation/cli.py`; narrow dispatch in `src/job_automation/cli.py`; `config/evaluation.example.json`; `tests/{test_cli_evaluation.py,evaluation/test_windows_paths.py,evaluation/test_windows_restart.py,evaluation/test_integration.py}`; `tests/manual/evaluation_smoke.py`; future component handoff and narrow README usage notes.

**Tasks.** Require explicit external workspace/input settings, safe diagnostics and distinct nonzero exits for invalid setup versus incomplete execution. Reports identify offline fake transport, native Windows, live local model, reviewer quality and RUN integration evidence separately. Test real evaluator/selector/provider composition with only transport/time faked. Verify restart, changed CWD, spaces/non-ASCII paths, file-handle release, bounded retries and no publication. Run live paired measurements only after EG5 and controlled-run gates pass; missing dependencies yield pending checks with owners and next actions.

**Acceptance criteria.** A user can recreate a report from frozen records without new inference and resume an incomplete pair without duplicating committed work. Native subprocess checks establish Windows behavior separately from generic tests. The handoff lists exact versions, manifests, commands, measured counts, unavailable tests and unresolved gates. G2 is not claimed complete without real comparison evidence and RUN integration. No Salesforce smoke write is part of evaluation acceptance.

**Tests.** CLI validation/redaction, whole fixture workflow, correction import/report regeneration, rejected export sampling, subprocess kill/restart and fail-closed publication matrix from S03. Run affected assessment/context/model/storage/contract tests after implementation; broaden only for actual integration changes. Existing fake-test pass totals are not a substitute for new EVAL checks.

**Configuration / migration impact.** Add a non-secret example with placeholders, loopback model configuration, explicit corpus/output roots and versioned metric/review settings. No scheduling, remote credentials or notification configuration. Keep EVAL migration history separate; do not renumber production migrations.

### EVAL-01-S09 — Extend paired evaluation to document claims (DEFERRED, Phase 1)

**Objective / requirement and contract references.** Compare JSON/RAG document grounding, unsupported claims and editing effort after generation exists. R13/R11/R06/R15; C01/C06/C08–C10/C13/C14; blueprint §5 draft accuracy and §7 G4.

**Dependencies.** S01–S08; **implemented GEN-02 input freezing/context, GEN-03 content generation, GEN-04 validation**, with their handoffs and compatible versions; LLM-01/CONTEXT-04 and Phase 1 MODEL-02 measurements. GEN-01 is required for any request-worker integration lane. C13/C14 schema presence alone does not unblock this story.

**Inputs → outputs.** Synthetic/local frozen generation requests, same profile/posting/model, language/template options and purpose permissions → paired CV and optional cover-letter C14 content, claim-level gold/review records, validator outcomes and document-quality reports.

**Owned files.** Future `evaluation/{document_records,document_adapter,document_metrics}.py`; `tests/evaluation/documents/{test_pairs,test_claims,test_review}.py`; synthetic document-evaluation fixtures. No generator or validation implementation belongs to EVAL.

**Tasks.** Adapt the controlled-pair manifest to generation prompt/schema versions, language, document type and frozen template options; hold each constant within a pair. Use GEN-02 services without polling or creating live Salesforce requests. Measure retrieval/admission/use independently for document purpose. Label candidate claims against C01 and job/employer claims against frozen C06; distinguish subjective motivation from factual claims. Review altered dates/titles/metrics, invented skills and subtle exaggerations such as contributed → led despite valid IDs. Record validator catches/misses separately from reviewer judgments, original/edited drafts and active editing effort.

**Acceptance criteria.** Both strategies use identical approved facts and purpose permissions. No document approves itself; evaluation reviews are labels, not production approval. Unsupported claims remain visible even if schema/reference checks pass. Missing generation services produce a deferred gate, not fake production-quality results. Request/worker state and Salesforce remain untouched.

**Tests.** After dependencies exist: same-input paired draft capture; forbidden claims, restricted evidence, invalid candidate/job citations, paraphrase inflation, German/English text, unknown dates, unavailable-job policy and prompt injection. Check unchanged controls and zero polling/upload/notification/approval calls.

**Configuration / migration impact.** Future versioned document rubric, purposes, languages and generator/template references; additive EVAL-only records. No Phase 1 code/configuration is enabled by Phase 0 implementation. Generation prompts/settings remain owned by GEN components.

### EVAL-01-S10 — Evaluate rendered drafts and retained review versions (DEFERRED, Phase 1)

**Objective / requirement and contract references.** Measure readable artifacts, rendering failures and reviewer effort while preserving local-only evaluation. R13/R11/R12/R14/R16; C13/C14 artifact, delivery and approval distinctions; blueprint §§5/7/9.

**Dependencies.** S09; **implemented GEN-05 rendering/local version checkpoints** and GEN-02–04. **GEN-01/GEN-06 and SF-07/08** are additional gates only for an imported, read-only delivery/review-history analysis lane; their actual delivery verification stays with those owners. No evaluation-triggered upload is permitted.

**Inputs → outputs.** Validated paired drafts, frozen templates/renderer versions, local artifacts and reviewer edits → render-quality labels, hashes/version lineage, render latency/failure metrics and extended EVAL handoff.

**Owned files.** Future `evaluation/{artifact_review,render_metrics,document_reporting}.py`; `tests/evaluation/documents/{test_artifact_versions,test_render_failures,test_windows_rendering}.py`; local-only manual QA harness and handoff extension.

**Tasks.** Consume GEN-05's renderer rather than building one. Inspect DOCX and PDF for missing/truncated text, German characters, long bullets, multi-page layout, page breaks and readability; retain original and edited version references. Record renderer setup, conversion timeout/failure, size/pages, content retention and human layout ratings separately from claim correctness. Evaluate generation/validation/rendering latency separately; importing delivery history cannot mark local artifacts delivered or approved. Use local artifacts only for active runs.

**Acceptance criteria.** Readable output has actual visual-review evidence; a file existing or a schema passing is insufficient. Failed conversion remains a measured failure. Edits never overwrite original paired artifacts. Delivery readiness and candidate approval are separate from evaluation review completion. No upload, request transition, Salesforce File creation or readiness notification occurs.

**Tests.** After dependencies exist: missing renderer, timeout, malformed output, lost local checkpoint, retry reuse, Unicode/spaces/different CWD, long multi-page samples and original/edited hash lineage. Assert zero remote effects with fake delivery ports that fail if called. Real rendering and manual visual checks are separate from fake-renderer tests.

**Configuration / migration impact.** Future renderer/template/rubric versions and local artifact retention references only. Reuse GEN-05's isolated profile/timeout settings; EVAL does not select a paid renderer, provision Word, or configure delivery. Extend the EVAL schema compatibly and retain Phase 0 readers.

## Verification and handoff checklist

These are future implementation checks, not results measured by this planning task. Paths and CLI names above are proposals until their stories freeze them. A native test recipe, after the files exist:

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

The handoff must include:

- Story statuses, exact contracts/schema/software versions, owned files, configuration/migration decisions and EG1–EG5 evidence or pending owner/action.
- Unit/contract, fake integration, native process/Windows, live local model, reviewer-quality and RUN integration statuses separately. Current handoff test counts are historical; this story-planning task ran no application tests or evaluations.
- Corpus/split/label/sample manifests, frozen controls, model/prompt/index identities, actual case/review counts, complete/incomplete pairs, metric definitions/denominators, stage attribution, latency/usage provenance and uncertainty limits.
- Explicit no-publication evidence across normal execution, failure, resume, review import and sampling, including untouched production selected assessments and existing outbox work.
- Measured results with their experiment/report references. **No EVAL quality baseline or numerical target is established by this plan.** Proposed quality/latency targets must be labeled proposed, separately recorded, and never displayed as achieved measurements. Zero Salesforce effects is a required invariant, not an empirical quality target.
- Recommendations to CONTEXT-04/MATCH-02/POLICY-01/MODEL-02 with evidence and tradeoffs; no automatic tuning/promotion into production. S09/S10 remain deferred until generation owner handoffs and services exist. Phase 2 scheduling, automatic drafting and notifications remain outside EVAL-01.
