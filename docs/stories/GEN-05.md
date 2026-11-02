# GEN-05 — Rendering and local artifact version implementation stories

Status: **PLANNED — documentation only; implementation and verification pending**  
Date: 31 October 2026  
Component: **GEN-05 only**, Phase 1  
Direct requirements: **R11, R12, R14**; supporting constraints: R09, R15, R16  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), C13/C14, §§5–10 and gate G4  
Repository instructions: [README.md](../../README.md) and blueprint §§8–9. No applicable `AGENTS.md` was found in the repository paths or checked ancestor directories.

## Objective and boundary

Turn an exactly validated, saved structured draft into readable, editable DOCX and matching PDF files using approved local layouts. Save immutable output bytes, provenance, hashes and checkpoints before making artifacts available to delivery. A retry must reopen and verify valid saved artifacts, without repeating inference, rewriting content or invoking a renderer unnecessarily.

GEN-05 owns layout approval/selection, DOCX construction, local PDF conversion, output verification, local artifact versions and recovery. It owns the minimal GEN-01 adapter/storage/operations wiring required to uphold those guarantees. GEN-04 owns factual validation and render authorization; GEN-06 owns Salesforce Files uploads, upload reconciliation, remote IDs, delivery and review integration. This work does not create new candidate facts, translate factual content, repair drafts, approve documents, install software automatically, modify Salesforce, notify users, or implement Phase 2 scheduling.

The story decomposition, contract names, layout choices and numeric limits below are proposed engineering defaults. They are not additional confirmed user requirements. Template approval means approval of layout assets for use, separate from candidate approval of a particular document. No proposed template is already approved by this planning document.

## Repository evidence and dependencies

Paths abbreviated as `generation/`, `contracts/`, `storage/` or `operations/` are beneath `src/job_automation/`.

| Dependency / inspected evidence | Current state and planning consequence |
|---|---|
| **GEN-04**, direct prerequisite | **`docs/components/GEN-04.md` is absent.** [GEN-04 stories](GEN-04.md) are PLANNED, not a completed handoff. They propose `DocumentValidationReport` and `ValidatedDraftForRendering` 1.0, durable report reopening and a derived `allowed_for_review` gate. No concrete validator/gate implementation was found. Develop against explicit test fixtures until its real contracts and handoff are available; production rendering must remain blocked without that gate. Do not implement GEN-04 within GEN-05. |
| **DATA-01**, direct prerequisite | [DATA-01 handoff](../components/DATA-01.md) records VERIFIED storage, migrations, SHA-256 files and checkpoints on native Windows. Its historical migration head is 002; current code is at **012 (`012_draft_content`)**. Reinspect the head after GEN-04 is implemented. Allocate a new forward migration; never edit applied SQL/checksums. |
| Existing artifact persistence | `storage/filestore.py:save_artifact_file` hashes bytes but uses direct `write_bytes` to a sanitized filename, allowing replacement. `storage/repositories/artifacts.py` saves C14 metadata but does not verify bytes, enforce immutable version slots or atomically commit render completion. Add narrowly scoped publication/reopen operations; do not assume these helpers provide crash-safe immutable output. |
| Existing C14 | `contracts/artifacts.py:Artifact` 1.0 has UUID, request ID, integer version, format, absolute local path, byte hash, size, delivery/approval state, marker and UTC creation time. It permits zero bytes and lacks render/template/report provenance. Keep the reader and delivery/approval meanings; use versioned companion records for stronger GEN-05 invariants. Legacy metadata alone is not proof of valid rendered output. |
| **GEN-03**, content input | [GEN-03 handoff](../components/GEN-03.md) records offline/scripted-provider and native-Windows verification, with live model quality pending. This supersedes the older GEN-04 stories' statement that its handoff is absent. `contracts/draft_content.py` supplies `DraftDocumentV2` **2.0**, ordered sections/entries, atomic claims, protected values, localized headings and review issues. `candidate_name` is literally null; `validation_status` remains `pending_gen04` because a separate report owns validation. Legacy C14 v1 remains audit-readable, not automatically eligible for new rendering. |
| GEN-03 content specification | `generation/draft_prompts.py` freezes `content-basic` / `content-compact` 1.0 and `gen03-cv-extractive-v1` / `gen03-letter-extractive-v1`. These are **content specifications, not approved DOCX layouts**. Claims remain exact factual excerpts in their original language; `de`/`en` headings and bounded subjective phrases are localized upstream. Preserve this distinction and map compatible layout assets explicitly. |
| **GEN-02**, frozen inputs | `input_records.py` includes sealed template ID/version/content digest, requested language, context strategy and `output_formats`; code and receipt repositories exist, but its handoff is absent. Reuse the sealed options/read-only reopen boundaries. Rendering must not freeze current inputs again or select the latest profile/recipe. |
| **GEN-01**, integration | [GEN-01 handoff](../components/GEN-01.md), `ports.py`, `records.py`, `coordinator.py`, `recovery.py`, `worker.py` establish the worker boundary. `DocumentRenderer.render_document(draft, output_format, destination_path, op_id)` currently lacks checked validation input. Rendering trusts completed checkpoints and existing delivery slots without reopening bytes; destinations are request-level filenames; slots and artifacts are saved separately. The checkpoint result path is hardcoded to DOCX, while formats come from mutable worker settings. These require narrow integration changes. |
| Delivery slot constraint | Migration 010 has `UNIQUE(request_id, artifact_format)` for `generation_artifact_deliveries`. Preserve its role as an active delivery pointer; immutable render history must have its own request/version/format key. Never replace a slot already dispatched or awaiting ambiguous-upload reconciliation. |
| Retry enforcement gap | `GenerationRetryPolicy` declares attempt/backoff limits and the repository exposes `record_attempt` / `list_attempts`, but inspected coordinator rendering does not enforce those limits or persist rendering attempts. Reuse these contracts and implement enforcement narrowly for rendering; do not describe configuration alone as an existing durable retry guarantee. |
| **RUN-01 / OPS-01**, supporting | Reuse the Windows worker lock shared by search and generation. `operations/inventory.py`, `backup.py` and `relocation.py` know existing artifact paths and unfinished requests; register new render records, receipts and template snapshots with retention/restore. Avoid a second lock system or backup framework. |
| Runtime/configuration | `pyproject.toml` requires Python >=3.12 and currently lists Pydantic/tzdata plus test extras; no DOCX/PDF packages are declared. No approved `templates/` catalog or concrete renderer exists. LibreOffice installation, fonts, versions and actual native output remain unverified by this task. |
| **GEN-06 / SF-07/08**, downstream | Supply saved exact artifacts and review references through a local boundary. Use a delivery spy in GEN-05 tests. Remote accessibility, notifications and human approval remain downstream acceptance, not evidence of GEN-05 completion. |

## Windows approach evaluation

**Proceed with python-docx plus local LibreOffice as the proposed default, subject to the native fixture gate in S07.** python-docx creates and updates DOCX files, including paragraphs, lists, tables and styles. It is the document construction layer; PDF conversion and final pagination require a separate renderer. Current documentation identifies release 1.2.0; pin a tested compatible dependency set during implementation rather than treating this document as a lockfile. [python-docx documentation](https://python-docx.readthedocs.io/en/latest/)

LibreOffice documents `soffice.com` for Windows console use, `--headless`, explicit output directories, PDF export filters and `-env:UserInstallation` for a non-default profile. Its user profile must be writable. This supports a native local adapter without a Word license, cloud service, WSL or Docker. The command interface does not itself establish output correctness or crash recovery. [LibreOffice startup parameters](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html)

Proposed adapter argument shape, **not a shell command or completed smoke test**:

```text
[absolute_soffice_com,
 "-env:UserInstallation=" + isolated_profile.resolve().as_uri(),
 "--headless", "--nologo", "--nodefault", "--norestore",
 "--convert-to", "pdf:writer_pdf_Export",
 "--outdir", absolute_empty_attempt_output_dir,
 absolute_saved_docx_path]
```

Use a Python subprocess argument list with `shell=False`, an explicit working directory and hidden native process startup. Never interpolate content into PowerShell/cmd, use a model-supplied executable/filter, or require shell activation. Prefer explicitly configured absolute `soffice.com`; discovery may suggest a path for configuration but must not silently switch binaries. Generate the profile URI with `Path.as_uri()` so spaces, umlauts and URI-reserved characters are encoded correctly. Do not use `--nolockcheck`, the user's interactive profile, or a shared writable profile.

This is a separate desktop program with font/layout behavior that must be measured on the target machine. Word and LibreOffice can paginate the editable DOCX differently; the saved PDF represents the recorded converter/font environment. No byte-identical fresh-render promise or universal visual equivalence is made. Cache reuse preserves the exact original bytes. Missing fonts, output drift and unbounded page growth must be visible. If the native gate fails, record the limitation and evaluate a free local alternative separately; no silent backend substitution, paid API or mandatory Microsoft Word automation.

For verification, choose and pin a local PDF parser plus a Windows-capable page rasterizer during S01/S07, document their versions/licenses and installation requirements, and use actual parsing and page inspection. A parser can support text/page checks but cannot establish absence of clipped glyphs. Do not claim visual QA from file extensions or extracted text alone.

## Contracts and invariants to establish first

All proposed persisted/exchanged records use strict versioned schemas, UTC events, detached reads and `sha256:<hex>` digests. Export schemas and synthetic fixtures. Use existing canonical UTF-8 JSON hashing for semantic records, with explicit self-hash exclusion; use SHA-256 of **exact file bytes** for artifacts. These are different hashes, not interchangeable identities.

| Contract / boundary | Required contents and behavior |
|---|---|
| GEN-04 `ValidatedDraftForRendering` 1.0, prerequisite | Verified C14 v2 payload/ref/hash, request/input binding, durable validation report ref/hash, content-spec identity and persistent review obligations. Reopen through GEN-04's trusted gate before new rendering and saved-artifact reuse. A caller-created envelope, `ValidationReport(is_valid=True)` or completed checkpoint cannot authorize work. Fatal, incomplete, absent, mismatched or corrupt reports block all rendering/delivery. |
| `ApprovedLayout` 1.0 | Layout ID/version/digest; asset manifest and hashes; allowed document type, language, C14 schema and content-spec/recipe digests; margins/page dimensions/styles/font requirements; static localized labels and optional content rules; approval actor/time/evidence; immutable approved status. Approval binds exact assets, configuration and rendering rules. Unknown, changed or unapproved assets cannot be used for a new render. |
| `RenderSpecification` 1.0 | Request and draft/receipt IDs/hashes; GEN-04 report/binding/review refs; frozen option/content-spec hashes; selected layout snapshot; requested formats; layout engine/python-docx/converter versions and identity; font manifest; conversion filter and settings; output-validation policy version. Persist before side effects. Retain upstream model/prompt/context provenance by verified references, not by regenerating it. |
| `RenderIntent` / `RenderAttempt` 1.0 | Stable logical render key, request, reserved artifact-set version, output artifact UUIDs/markers, specification hash and expected relative paths; separately identified bounded execution attempts, step, start/end, reason codes and owned staging/profile/process references. Retries preserve the logical key, reserved version and artifact IDs; wall-clock attempt IDs never determine cache identity. |
| `RenderedArtifactReceipt` 1.0 | Artifact/request/set IDs, version/format, render-spec hash, draft/report/layout bindings, byte hash/positive size, media type, output-check outcomes, creation time; PDF receipt additionally binds the exact source DOCX artifact ID/hash. Include local review-package ref/hash. Store immutable payload separately from relocatable physical paths and mutable delivery/approval fields. |
| `ArtifactSet` 1.0 | Request/set/version, required formats from the sealed request, exact artifact IDs/receipt hashes, completeness, review reference and set hash. Both DOCX and PDF are the normal supported output set. A partial set is persisted and inspectable but cannot complete rendering or enter delivery. Reject unsupported format selections; never reduce the set when a renderer is missing. |
| `LocalRenderResult` 1.0 | Either a completed verified set, a recoverable/blocked outcome with saved partial references, or a classified failure. Success requires reopenable files and committed receipts. It cannot assert remote delivery, readiness or approval. |
| Versioned renderer port | Proposed `render_or_reopen(validated_input, render_spec_ref)` returns `LocalRenderResult`; `reopen_artifact_set(set_ref)` verifies saved state and authorization without inference/conversion. Use an explicit v2-capable GEN-01 adapter; remove permissive legacy render fallbacks from production. The service chooses managed paths, not an arbitrary caller destination. |

### Template selection and content fidelity

- Map each frozen `content-basic` / `content-compact` spec, type and language to an approved layout version explicitly. Initial proposed layouts are simple A4, single-column CV/letter variants, with 11-point body text, readable spacing, stable heading styles and a minimum 10-point body size. These are testable starting choices, not candidate preferences or mandatory one-page limits.
- Pin layout selection at the **first render intent**, since the existing GEN-02 seal contains a content-template digest, not physical layout assets. Persist the approved layout snapshot/digest without rewriting the upstream seal. Resume the pinned selection even if catalog defaults change. Future freeze-time layout selection requires an explicit GEN-02 contract change; do not conflate the two digests now.
- Copy approved layout assets into durable managed storage by digest when pinning. New requests may select a newer approved version; retries may not switch. If an approval is explicitly revoked, block new conversion and record the reason; historical artifacts stay inspectable. Catalog retirement alone does not rewrite prior approvals or delete snapshots.
- Render ordered sections/entries, claims and subjective blocks once, preserving order, role grouping, candidate-versus-job attribution and exact text. Define section-level content before entries and claim-list order before subjective-list order where C14 provides separate arrays; do not infer unavailable interleaving. Use stable claim/entry-to-paragraph mappings in the local receipt for QA.
- Preserve original factual language, punctuation, protected values, dates and precision. No translation, number/metric rewriting, invented names/contact details, inferred “heute/Present”, experience totals, salutation or signature. Initial release leaves dates in their validated textual form; display localization would need a later reviewed transform contract. Missing identity/contact remains omitted with the upstream warning visible in the review package.
- Layout may wrap text and add approved static document/draft labels, bullets and page numbers. It must not add connective factual prose or silently truncate content. Avoid fixed-height text boxes and layout tables that clip content. Keep headings with following text; permit oversized bullets to split across pages. Paragraph pagination controls support these policies, but their actual result needs rendering checks. [python-docx pagination properties](https://python-docx.readthedocs.io/en/latest/user/text.html#pagination-properties)
- Preserve review obligations in a durable local review package linked to both formats and the validation report. Show a localized draft/review notice such as `Entwurf – vor Verwendung prüfen` / `Draft – review before use`. Keep detailed evidence, private source quotations and diagnostics out of the CV/letter body, file metadata and ordinary logs. Review-package delivery/UI is a GEN-06 handoff requirement.
- Templates are application-controlled, macro-free local assets; source text is inserted as text, never executable fields, expressions or arbitrary OOXML. Reject external template relationships, linked resources, macros and unexpected embedded objects. Do not fetch images/fonts/URLs during rendering. Inspect and clear author/company/template metadata that could leak workstation identity or sample content.

### Identity, versions and save-before-delivery protocol

Use managed paths such as `artifacts/<request_uuid>/v0001/<artifact_uuid>.docx` and `.pdf`, plus receipts/layout snapshots under documented managed subdirectories. Staging and profiles live in request/attempt-owned subdirectories under the configured writable data root. Python uses `pathlib.Path`; relative references resolve against that root, never process CWD. Keep filenames UUID-based so employer names cannot become reserved Windows names, traversal paths or collisions. Validate resolved containment, including reparse-point/junction escapes, before writing or cleanup.

Version semantics:

1. One immutable artifact-set version groups the required DOCX/PDF pair; each file has a distinct artifact UUID and byte hash. Reserve version 1 and identities transactionally before work. Enforce unique `(request_id, artifact_version, format)` in new render tables and a unique logical-render key; duplicate callers return the committed/reserved logical result.
2. A retry never increments the artifact version, overwrites committed bytes, or allocates a second successful result for the same intent. A changed input, content, requested template or language is a **new generation request** under GEN-01, preserving predecessor links; its local version sequence starts independently.
3. Schema/storage support immutable higher versions, but this release need not expose an in-place rerender command. Any future explicit technical rerender of the same content reserves a new version and marker, retains prior artifacts and approval, and must coordinate active delivery pointers. Never change a dispatched/uncertain/delivered slot as retry recovery. For this release, missing/corrupt committed artifacts require exact-byte restoration or an explicit new request, not silent replacement under the old ID/hash.

Publication protocol:

1. Acquire/reuse the existing worker lock; validate the GEN-04 gate and look for saved receipts **before** requiring installed rendering software. For new work, pin the render specification, reserve IDs/version/paths and persist intent. Do not keep a SQLite write transaction open during conversion.
2. Build DOCX in a unique same-volume staging directory, close all handles, verify its structure/text, calculate hash/size and persist a prepared receipt with expected bytes/path. Flush appropriately before promotion. Promote without replacing an existing final file, then reopen and verify the final bytes. Commit Artifact metadata, immutable receipt and per-format completion together using a transaction-aware repository operation.
3. Convert **that saved DOCX** to PDF in a fresh attempt output directory. Validate, hash, prepare, promote and commit PDF similarly. Bind the PDF to the DOCX byte hash. A PDF failure retains the valid committed DOCX and only retries conversion. Never regenerate the DOCX as a conversion retry.
4. When all required formats reopen successfully and authorization/review refs remain intact, atomically commit the completed set, active delivery pointers, rendering checkpoint and local request `upload_pending` transition. Set `result_artifact_ref` to the documented set/result reference and exact members, replacing the hardcoded guessed DOCX path through an explicit consumer migration.
5. Only then hand exact saved artifacts to GEN-06. Before dispatch, the adapter reopens the set and verifies paths/hashes/binding again. Artifact approval starts `draft`; local completion does not imply remote accessibility or `ready_for_review`. GEN-06 owns remote marker reconciliation and readiness after delivery.

A filesystem rename and SQLite commit are not one transaction. The prepared intent/receipt is essential: on restart a promoted file without committed metadata may be adopted only after matching its reserved identity, expected hash/size, full spec/report binding and output checks. Unbound or mismatched files are quarantined/held for inspection, never guessed into successful output. Partial staging is disposable after ownership checks. Process-crash recovery is required; do not claim power-loss guarantees from the existing SQLite `synchronous=NORMAL` setting or from rename alone. Record durability limits and verify integrity after restart/restore.

### Conversion lifecycle, failure handling and output validation

Use one conversion at a time. Every attempt receives its own empty output directory and writable profile, including retries. Probe executable/version and profile/output writability with bounded time before conversion; diagnose missing dependency, unsupported version or permission failure without launching a GUI or downloading software. Proposed initial conversion timeout: **120 seconds**, configurable and measured in S07; terminate/grace cleanup bound: **10 seconds**. Reuse GEN-01's retry policy (currently five maximum stage attempts by default) and attempt repository, adding durable enforcement for rendering. Persist attempt count and next eligible retry time before another launch; do not add nested unlimited retry loops or reset counts at process restart. Budget exhaustion leaves an explicit inspectable failure, not another automatic attempt.

The subprocess wrapper must own and track the launcher and converter descendants, including `soffice.bin`. Choose and verify a native Windows process-tree containment/termination mechanism, such as a kill-on-close Job Object, during implementation. On timeout/cancellation/worker death, stop only processes belonging to that attempt, wait within the cleanup bound and release handles. Never terminate all LibreOffice processes by image name or disrupt a user's open Writer session. If descendants cannot be proven stopped, block further conversion, retain the profile/output quarantine and report cleanup failure. Do not remove a live profile. Profile cleanup failure after successfully committed output is a diagnostic, not permission to discard that artifact or rerender it.

| Condition | Required result and retry policy |
|---|---|
| Missing python-docx, converter, configured layout or verification dependency | `missing_configuration`, specific reason such as `renderer_missing` / `layout_unavailable`; stage blocked. Preserve saved work. Resume after remediation; no silent DOCX-only completion. Fully saved valid sets can reopen without conversion dependencies. |
| Profile/output inaccessible; executable denied | `permission`, `renderer_profile_unwritable` / `render_path_denied`; block until corrected. No fallback to the interactive/default profile or another directory. |
| Conversion timeout/cancel/process launch failure | Timeout is `transient_service` with `renderer_timeout`; persist elapsed time/attempt, terminate owned tree and retain DOCX. Retry only within existing bounded policy with a fresh isolated profile. Cancellation retains resumable state without inventing success. Distinguish missing binary and denied execution from transient launch failure. |
| Nonzero exit, including a PDF left behind | No successful publication from that attempt; classify known permanent configuration/input problems appropriately, otherwise bounded `transient_service`/`renderer_failed`. Capture bounded redacted diagnostics locally; never echo document text or personal paths remotely. |
| Exit zero but missing, stale, empty or unreadable output | `validation` / `render_output_invalid`; no artifact success or delivery. No semantic regeneration loop. Require diagnosis/remediation before explicit retry of the same intent. |
| Disk full or known capacity shortfall | `capacity`, actionable local failure with partial work retained. Apply bounded retry after remediation; no cleanup of history or valid DOCX to hide the failure. |
| Sharing violation from a temporary file lock | Classified bounded transient failure after confirming the intended managed path. Persistent access denial is `permission`, not an endless transient retry. |
| Missing or hash-mismatched committed artifact/report; conflicting final destination | Integrity failure; block reuse and delivery. Never adopt new bytes as the old artifact, silently rerender, or copy an old approval to a replacement. |
| Saved DOCX valid, PDF absent | Reopen DOCX/report/intent, verify pinned converter/fonts/settings for remaining work, then convert only PDF. A changed converter environment blocks pending conversion until the pinned environment is restored or a new request is chosen. |
| Saved set valid, converter later removed or catalog defaults changed | Reuse exact files/IDs/hash/markers with zero converter or model calls; validate integrity/authorization through local readers. Installed renderer/version checks apply to new conversion, not cached byte reuse. |

Minimum output checks:

- **DOCX:** positive bounded size, valid ZIP/CRC and required OOXML parts, reopen using the DOCX reader, expected nonempty paragraphs, ordered claim/subjective coverage and no leftover placeholders. Check all relevant body/header/footer content, approved static labels and unsafe relationships/embedded parts. Treat invalid XML characters as explicit unsupported input, not silently deleted facts.
- **PDF:** require the exact expected basename in the fresh attempt directory, a regular contained file, positive bounded size, PDF signature and successful independent parsing; reject encrypted/unreadable files, zero pages, empty expected text and missing/truncated content. Verify page dimensions, page count bounds, expected headings/claim text and source DOCX linkage. Header/magic checks or return code alone are insufficient.
- Compare extracted text with a versioned normalization policy limited to layout whitespace, line wrapping and known PDF glyph/ligature behavior. Do not normalize away umlauts, `ß`, numbers, signs, qualifiers or meaningful punctuation. No timestamp-only freshness test; fresh attempt isolation and expected receipt/hash establish provenance. Keep hard size/page limits configurable and explicit, never truncate to meet them.
- Rasterize every page of acceptance fixtures; inspect glyphs, clipping, bullet indentation, headings, page breaks, margins, footer overlap and blank trailing pages. Use automated geometry/text checks where reliable and a recorded visual approval gate for each supported layout/font/converter combination. Runtime structural checks do not certify perfect visual layout or factual truth; candidate review remains required.

## Implementation stories

Execute S01 → S02 → S03 → S04 → S05 → S06 → S07. S03/S04 may use a temporary persistence adapter in tests until S05 is available; production wiring waits for durable publication. All stories are **PLANNED**. Listed filenames are proposals, not existing implementations.

### GEN-05-S01 — Establish rendering contracts and prerequisite gates

**Objective:** Define validated input, approved layout and durable render result boundaries before business logic.  
**Requirements:** R11/R12/R14; supporting R15/R16.  
**Dependencies:** GEN-04 report/gate handoff, DATA-01, FND-01; GEN-01/02/03 interfaces.  
**Owned files:** proposed `generation/render_records.py`, `render_ports.py`, `render_settings.py`; narrow `generation/ports.py`, schema exports and `schemas/v1/` additions; synthetic contract fixtures.  
**Inputs → outputs:** actual upstream contracts and the contract table above → strict rendering schemas, explicit adapters and compatibility decisions.

Tasks:

- Reconcile GEN-04's implemented envelope/gate with these proposals; record missing handoff/acceptance rather than substituting a Boolean validator. Require C14 v2 support and genuine trusted reopen on every entry/resume path.
- Define semantic hashes, byte hashes, relative managed refs, positive artifact size, required-format completeness, prepared/committed states and deterministic logical keys. Persist dependency/version fingerprints without personal data in diagnostics.
- Preserve `Artifact` 1.0 and legacy readers; add companion receipts/set schemas. Version incompatible port/result-reference changes explicitly and update consumer fixtures. Legacy rendering checkpoints cannot be upgraded to trusted success by filling default hashes.
- Define strict non-secret renderer configuration, absolute path/base resolution, unsupported format behavior and timeout/size/page/font limits. Pin compatible DOCX/PDF verification dependencies during implementation; LibreOffice remains separately installed local software. Record native Windows support evidence for each selected dependency.

Acceptance: valid records round-trip; wrong request/report/draft binding, unknown formats, duplicate format slots, zero-byte success, partial-set completion or false approval are rejected. Default-success legacy reports cannot reach a renderer. Contract tests need no model, converter or Salesforce.

Tests: `tests/generation/rendering/test_contracts.py`, `test_compatibility.py`, `test_settings.py`, affected contract/schema tests. Configuration/migration impact: schema/adapter and dependency declarations; no storage migration yet.

### GEN-05-S02 — Approve and pin layout assets without changing content

**Objective:** Provide reviewable local layouts compatible with frozen content specs and languages.  
**Requirements:** R11/R14; supporting R15/R16.  
**Dependencies:** S01; GEN-03 frozen recipes and GEN-04 required-content policy.  
**Owned files:** `templates/` asset/catalog documentation, proposed `generation/layout_catalog.py`, layout manifest fixtures and approval records.  
**Inputs → outputs:** approved layout assets plus frozen type/language/content spec → pinned compatible layout or actionable blocked selection.

Tasks:

- Produce simple A4 basic/compact layout variants for CV and requested cover letter, supporting `de`/`en` labels without changing factual source language. Share assets where appropriate while testing each mapping explicitly.
- Define style/font manifests, section/entry rendering rules, bullet and pagination settings, metadata sanitization, static review labels and omission behavior. Preserve source attribution and all review obligations.
- Establish explicit approval evidence for exact layout assets after representative visual checks; test fixtures may carry clearly synthetic approval records. Prevent unapproved runtime assets or changed bytes under an existing approved version.
- Snapshot the selected approved layout at first render intent. Verify compatibility with frozen spec digest and GEN-04 requirements; reject missing mapping without silently choosing another template.

Acceptance: changes to assets/configuration require a new layout version/approval; unsupported mappings block. A new default cannot alter an interrupted request. No candidate name/contact data is invented. Catalog loading and inspection cause no inference, network calls or output writes.

Tests: `test_layout_catalog.py`, `test_template_approval.py`, `test_content_mapping.py`. Configuration/migration impact: versioned approved catalog and managed layout snapshots; sample layouts stay proposed until approval evidence is recorded.

### GEN-05-S03 — Build and verify editable DOCX files

**Objective:** Render all validated content faithfully with python-docx and reject incomplete output.  
**Requirements:** R11/R14; supporting R15.  
**Dependencies:** S01–S02, GEN-04 gate.  
**Owned files:** proposed `generation/docx_renderer.py`, `render_projection.py`, `render_checks.py`; `tests/generation/rendering/` and synthetic fixtures.  
**Inputs → outputs:** verified draft and pinned layout → staged DOCX with content mapping and validation receipt, or classified failure.

Tasks:

- Implement exact ordered projection of headings/sections/entries and linked claims/subjective blocks. Prevent text loss through style replacement or run splitting; no mutable profile/context reads.
- Use semantic paragraph styles, hanging list indents, spacing and sensible page-break rules. Permit long paragraphs to flow rather than enforcing a one/two-page CV or a one-page letter by deleting text or shrinking below the approved minimum.
- Produce a visible draft notice and local review-package linkage. Strip sample text and personal document metadata. Reject unsafe template parts/relationships and invalid source characters without modifying protected values.
- Reopen the resulting OOXML and verify expected content coverage/sequence, safe parts and positive size before returning staged success. Close all file handles before later conversion/promotion.

Acceptance: DOCX opens as editable paragraphs/lists; German text, long bullets and all final-page content are present. Exact source dates, titles and metrics survive. Letter-only requests do not generate a CV. No fatal/incomplete validation input results in a staged file.

Tests: `test_docx_content.py`, `test_docx_structure.py`, `test_review_package.py`, `test_inert_source_text.py`. Configuration/migration impact: pinned DOCX dependency and layout settings; no remote integration or factual-content migration.

### GEN-05-S04 — Convert saved DOCX to PDF with isolated Windows processes

**Objective:** Make local conversion bounded, diagnosable and independent of the user's interactive LibreOffice session.  
**Requirements:** R11/R12/R14; supporting R15/R16.  
**Dependencies:** S01–S03; saved-DOCX port, RUN-01 serialization.  
**Owned files:** proposed `generation/libreoffice_converter.py`, `render_process.py`, `pdf_checks.py`; renderer health/config diagnostics and converter test fixtures.  
**Inputs → outputs:** verified saved DOCX/hash and pinned converter spec → validated staged PDF bound to that DOCX, or explicit failure.

Tasks:

- Implement executable/version/dependency checks, attempt-specific writable profile creation and URI encoding, empty output directories, argument-list invocation and bounded hidden process execution. Serialize public conversion entry points with the established lock ownership.
- Implement and natively verify descendant containment, cancellation, timeout and cleanup. Prove that worker termination leaves no converter holding the active profile; preserve owned leftovers safely when cleanup fails.
- Apply the failure table and independent PDF checks. Capture exit code, elapsed time, bounded safe diagnostics and environment versions. No stdout success-string parsing as the sole success test.
- Convert the committed DOCX bytes only. For remaining work after restart, verify the pinned converter/font environment instead of silently changing output under the same intent.

Acceptance: missing renderer produces an actionable blocked result; timeout is bounded including cleanup, leaves saved DOCX intact and creates no successful PDF receipt. Zero exit with no/invalid output fails. Existing interactive LibreOffice remains running and untouched. Space/Unicode paths work in native conversion.

Tests: `test_converter_failures.py`, `test_pdf_checks.py`, `test_process_cleanup.py`; explicit fake executable cases plus native `test_libreoffice_integration.py`. Configuration/migration impact: local converter path and limits; optional native helper dependency must be justified/pinned. No automatic installation.

### GEN-05-S05 — Persist immutable artifact versions and recover publication

**Objective:** Save completed outputs and hashes with recoverable per-format checkpoints before delivery.  
**Requirements:** R12/R14; supporting R09/R16.  
**Dependencies:** S01–S04, DATA-01, OPS-01.  
**Owned files:** proposed `storage/repositories/render_artifacts.py`, `generation/render_store.py`, `render_recovery.py`; narrow filestore/engine/migrations/repository changes and operations reference hooks.  
**Inputs → outputs:** render intents and checked staged files → durable Artifact/receipt/set records, or inspectable partial/failure state.

Tasks:

- Add a forward migration after the actual head for render intents, attempts, immutable format receipts and sets, uniqueness and dependency links. Preserve legacy Artifact rows and delivery/approval records; do not infer missing provenance from old paths.
- Implement same-volume staged publication, durable prepared receipts, no-clobber promotion and final reopen/hash checks. Use a transaction-aware composite save; existing repository methods with their own `with conn` must not accidentally commit only half of a compound operation.
- Recover every filesystem/DB boundary according to the publication protocol. Adopt only matching prepared files; preserve/quarantine conflicting bytes. Reuse valid committed DOCX/PDF without conversion and keep failed-attempt audit records separate from logical output.
- Register drafts, reports, pinned layouts/fonts/specs, review packages, prepared files and committed artifacts as protected dependency chains. Extend backup/relocation for companion refs and reconcile absolute Artifact paths after restoring elsewhere, without changing byte hashes or semantic identities.

Acceptance: crashes before/after promotion, artifact commit and set completion produce no duplicate successful logical artifacts or delivery of partial sets. Valid saved DOCX survives failed PDF conversion. Duplicate completion is idempotent; a conflicting hash at a reserved path blocks. Restore to a new root reopens the same set and hashes.

Tests: `test_artifact_store.py`, `test_version_uniqueness.py`, `test_crash_matrix.py`, `test_retention_restore.py`, populated migration upgrade/rollback tests. Configuration/migration impact: one or more new forward migrations, managed subdirectories and OPS-01 hooks; no wholesale storage rewrite.

### GEN-05-S06 — Integrate saved-artifact reuse and the GEN-06 delivery boundary

**Objective:** Make initial and resumed worker paths obey the same validation, persistence and completeness gates.  
**Requirements:** R11/R12; supporting R16.  
**Dependencies:** S01–S05, GEN-01, implemented GEN-04 gate; GEN-06 represented by a spy.  
**Owned files:** proposed `generation/render_service.py`, `render_adapter.py`; minimal `coordinator.py`, ports, records/recovery/composition and result-reference consumer changes.  
**Inputs → outputs:** request and checked draft/report → saved complete set and local upload-pending handoff, or blocked/failed resumable work.

Tasks:

- Replace checkpoint/delivery-slot early success with trusted report and artifact-set reopening. Use sealed `output_formats`; validate worker configuration compatibility without letting mutable defaults change existing requests.
- Restore per-format progress from committed receipts; repair a missing aggregate checkpoint without rendering. No new model call, content generation, retrieval or GEN-02 re-freeze is allowed during render/delivery retry.
- Commit set/checkpoint/request state/delivery pointers together after files exist. Replace hardcoded result filenames with explicit set/member references and update affected local consumers/fakes through the documented compatibility adapter.
- Persist a stable request/artifact/version reconciliation marker before delivery. Supply exact IDs, byte hashes, size, format, path, render/report refs and review obligations to GEN-06. A delivery retry or ambiguous upload cannot cause renderer invocation or slot replacement.
- Preserve the approval/delivery distinction and GEN-01 failure/retry policy. Use safe reason codes and IDs in status reporting; no document text in error messages.
- Wire rendering attempt accounting and persisted backoff eligibility into the adapter/coordinator. Verify restart cannot reset the budget, multiple formats cannot multiply it silently, and exhausted/nonrecoverable failures cannot be automatically requeued. Keep broader worker retry redesign outside this component.

Acceptance: fake delivery observes every required file already closed, saved, hash-verified and committed. An upload failure preserves the set and `upload_pending`; retry hands off identical bytes and IDs with zero rendering calls. No ready-for-review notification or approval originates in GEN-05. A completed checkpoint with missing/corrupt bytes or report blocks delivery.

Tests: `test_worker_adapter.py`, `test_saved_reuse.py`, `test_delivery_boundary.py`, affected GEN-01 crash/recovery tests. Configuration/migration impact: explicit port/result-reference migration; no Salesforce API/schema changes and no implementation of GEN-06 reconciliation.

### GEN-05-S07 — Verify native fixtures, document installation and hand off

**Objective:** Demonstrate local rendering/readability/recovery guarantees and record actual limitations.  
**Requirements:** R11/R12/R14; supporting R09/R15/R16.  
**Dependencies:** S01–S06, real GEN-04 integration for final acceptance, local LibreOffice/fonts/PDF QA tools.  
**Owned files:** `tests/generation/rendering/`, `tests/fixtures/generation/rendering/`, proposed `tests/manual/gen05_render_smoke.py`, `config/rendering.example.json`, relevant README instructions and future `docs/components/GEN-05.md`.  
**Inputs → outputs:** synthetic fixture matrix and native environment → measured results, approved layout evidence, operational instructions and downstream handoff.

Tasks:

- Execute the fixture matrix below for both document types, both languages, compatible basic/compact layouts and JSON/RAG provenance. Construct integration inputs through real upstream services with scripted model transport; distinguish gate fakes from real GEN-04 acceptance. Rendering itself never calls the model.
- Reopen every DOCX, parse every PDF and inspect every rasterized page. Record expected content, page counts, font coverage, elapsed times and peak memory on the actual Windows computer. Keep shared artifacts synthetic; machine-specific output lives in a fresh runtime/test directory.
- Provide quoted native PowerShell setup/health/render/test instructions, explicit executable/config/data paths and actionable missing-renderer diagnostics. Exercise a non-repository working directory and a data root containing spaces/non-ASCII text.
- Test restart, timeout/cancellation/descendant termination, locked/unwritable paths, populated migration and restore. Keep the user's active LibreOffice session intact. Record approved converter/font/layout combinations and any pending native cases.
- Write the component handoff with changed files, schemas/migration/dependency versions, exact commands/results, approved templates, installation prerequisites, limitations and GEN-06 contracts. Do not claim G4 or remote readiness from local/fake delivery tests.

Acceptance: every applicable story and fixture has recorded evidence. Native conversion/visual gates cannot be marked verified when skipped because LibreOffice/fonts are absent. Mark implemented with pending verification where appropriate; source-code presence or mocked conversion is not a native rendering pass.

Tests: full component suite plus affected generation/contracts/storage/operations checks and native smoke/crash fixtures. Configuration/migration impact: documented non-secret examples and actual tested dependency versions; Phase 2 startup/logged-out behavior remains deferred.

## Required fixture and acceptance matrix

All text/data is synthetic, including approval actors. Include expected exact content and source IDs; generated appearance alone is not a fixture oracle.

| Fixture / failure injection | Observable acceptance |
|---|---|
| German CV and letter with `Müller`, `Straße`, `Größe`, `Prüfung`, `äöü ÄÖÜ ß`, `€`, German quotation marks and en dashes | Correct Unicode survives DOCX reopening, PDF extraction and visual inspection; no missing-glyph boxes or ASCII substitution. Factual strings remain exact regardless of requested heading language. |
| English document with German source excerpts; German document with English source excerpts | Only upstream localized/static labels change. No factual translation or invented language proficiency. Original-language review issue survives. |
| Source metric `bis zu 20 %`, year `2021`, month `2021-03`, unknown end date | Preserve qualifier, value, spacing/precision and unknown omission; never render a precise invented date or ongoing employment. |
| A 1,200-character German bullet with several clauses; near-limit 4,000-character claim within C14 limits | Wrap and, when needed, flow across pages without truncation, overlap or tiny-font fallback. First/last words and all numeric tokens survive both formats. Oversized text beyond contract limits fails clearly. |
| Synthetic long compound word/URL, tabs, explicit line breaks, `& < >`, shell-looking source text | Safe literal text; no command execution, external fetch or OOXML injection. Unsupported controls fail explicitly. Long-token wrapping/overflow policy is tested and never drops text. |
| Short one-page CV plus 3–5-page CV and at least two-page letter, within contract cardinalities | Every ordered entry appears exactly once, including last-page sentinel text. Headings remain attached, bullets align, headers/footers do not overlap and no accidental blank final page. Page count baselines bind the recorded layout/font/converter version. |
| Long bullet taller than available page area; heading at page boundary | Paragraph can split legibly; no endless keep-together pagination or forced blank page. No fixed-height clipping. |
| Missing name/contact; warning-only validation; subjective closing | No placeholders masquerade as facts. Visible draft notice and linked review package retain all obligations; approval stays draft. |
| Fatal/incomplete/mismatched GEN-04 report; old Boolean-only checkpoint | Zero DOCX/PDF/delivery calls, including resumed paths. |
| Data root `C:\Users\Example\Job Suche – Prüfung ä\Daten Größe`, template/executable paths containing spaces, another CWD | Native construction, conversion, profile URI, hashing, reopen and restore work. Also exercise `#` and `%` in a permitted test directory to detect incorrect URI escaping. |
| UUID filenames under that root; attempted traversal, reserved name, junction escape or output outside root | Only safe contained managed paths accepted. No writes/deletes outside the intended attempt/root. A valid non-ASCII root is not rejected by overbroad sanitization. |
| Missing executable/import, denied executable/profile, unsupported converter/font set | Clear classified reason, saved progress retained, no GUI/default-profile/cloud fallback. |
| Hung converter, cancellation, worker killed while child runs | Completion bounded by timeout/cleanup; owned descendants stop, active user LibreOffice survives, successor can use a fresh profile. Unresolved process ownership blocks conversion. |
| Exit 0 with no PDF, zero bytes, invalid signature, damaged xref, encrypted PDF or zero pages | Output invalid; no successful receipt, set or delivery. |
| Exit nonzero but apparently usable PDF; stale PDF from another attempt; wrong filename | Reject the attempt. Never confuse stale or partial output with current success. |
| PDF parser succeeds but expected final bullet is absent; visual clipping despite text present | Content check catches missing text; raster/visual gate catches clipping. Neither parser success nor matching hash alone proves readable output. |
| DOCX committed then conversion timeout; restart after partial success | Reuse DOCX UUID/hash/version, invoke conversion only for PDF, no inference. |
| Crash after prepared receipt, after promotion, after per-format DB commit, after set commit and before delivery | Recover same reserved IDs/version; adopt only prepared matching bytes; repair checkpoints; never upload partial/uncommitted output. |
| Complete set followed by renderer removal, template default update, model outage or failed upload | Verify and reuse saved set without renderer/model calls; output bytes/IDs/markers unchanged. |
| Tampered/missing committed file, report or layout binding; file modified by an editor | Block reuse and delivery. Exact-byte restore or explicit new request required; never overwrite the original or inherit approval. Editing/reimport workflow is outside GEN-05. |
| Disk-full promotion, antivirus/sharing lock, duplicate completion, database commit failure | Explicit bounded failure, no orphan adopted without proof, no false success, previous valid artifacts retained. |
| Backup/restore into a second Unicode root; retention preview while PDF unfinished | Referenced files/reports/layouts survive; paths relocate correctly; semantic and byte hashes remain valid. Unfinished work is protected. |

## Configuration, migration and verification impact

Proposed `RenderingSettings` binds an approved catalog, absolute converter executable, managed staging/profile locations, supported versions/fonts, validation-policy version and bounded timeout/resource settings. Requested language, template and output formats come from sealed request inputs. Do not add `skip_validation`, auto-approval, “ignore renderer errors”, silent font fallback or automatic DOCX-only success switches. Diagnostics may inspect dependencies without producing candidate documents.

Keep imports side-effect-free. Resolve config-relative asset paths against the explicit config/package base and runtime-relative paths against the configured data root. JSON examples must escape backslashes; Markdown links use `/`; runnable PowerShell uses native paths and quoting. Test paths on Windows rather than inferring support from POSIX tests.

New render tables/companion records must preserve existing Artifact 1.0, C14 v2 and checkpoint history. Enumerate affected adapters, result-reference readers, inventory/backup/relocation code and fixtures before migration. Preserve human approval and remote acknowledgment fields; no migration may turn legacy unchecked files into newly authorized artifacts. Verify upgrade from a populated migration-012 database and the actual post-GEN-04 head, idempotent repeated migration and rollback on injected failure.

The following are **planned implementation-time checks, not commands run or tests passed by this story-planning task**. Proposed new paths will exist only after implementation.

```powershell
$gen05Repo = (Resolve-Path '.').Path
$gen05Python = Join-Path $gen05Repo '.venv\Scripts\python.exe'
& $gen05Python -m pytest (Join-Path $gen05Repo 'tests\generation\rendering')
if ($LASTEXITCODE -ne 0) { throw 'GEN-05 component checks failed' }
& $gen05Python -m pytest (Join-Path $gen05Repo 'tests\generation') (Join-Path $gen05Repo 'tests\contracts') (Join-Path $gen05Repo 'tests\storage') (Join-Path $gen05Repo 'tests\operations')
if ($LASTEXITCODE -ne 0) { throw 'Affected integration checks failed' }
$gen05Temp = Join-Path $env:TEMP ('GEN-05 Prüfung ä ' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $gen05Temp | Out-Null
Push-Location -LiteralPath $gen05Temp
try {
    & $gen05Python -m pytest (Join-Path $gen05Repo 'tests\generation\rendering\test_windows_paths.py') (Join-Path $gen05Repo 'tests\generation\rendering\test_windows_restart.py') --basetemp (Join-Path $gen05Temp 'Daten Größe')
    if ($LASTEXITCODE -ne 0) { throw 'Native path/restart checks failed' }
} finally {
    Pop-Location
}
```

S07 must add the exact tested native converter/visual-smoke invocation with explicit paths and record Python, OS, PowerShell, python-docx, LibreOffice, parser/rasterizer and font versions. Test ordinary invocation without a shell-activated environment. Do not claim unattended reboot/logged-out support: AUTO-01 owns that Phase 2 check. A full regression run is appropriate after contract/storage/coordinator changes; do not repeat successful runs without a new change or unresolved failure.

## Implementation handoff checklist

- [ ] State GEN-05 status, R11/R12/R14 acceptance and remaining prerequisite gaps; supply the real GEN-04 handoff, distinguish the absent GEN-02 handoff from existing code, and retain GEN-03's offline/live verification distinction.
- [ ] List owned files, actual contracts/schemas, approved template IDs/versions/hashes and approval evidence, content-spec mappings and explicit compatibility decisions.
- [ ] Record tested native converter/dependency/font versions, installation/configuration paths, isolation strategy, timeout/process-tree behavior and actionable diagnostics.
- [ ] Document artifact/version/marker identities, prepared-publication protocol, transaction boundaries, result refs, review refs and supported legacy behavior.
- [ ] Demonstrate save-before-delivery, per-format recovery, same-byte reuse without renderer/model services, corruption blocking, migration preservation and restore/retention protection.
- [ ] Record unit/contract results, real SQLite tests, fake-converter failures, real LibreOffice conversion, every-page visual QA, actual GEN-04 integration and fake GEN-06 delivery separately. Missing native tests remain pending.
- [ ] Hand GEN-06 exact artifact/set/review contracts and the delivery-spy evidence; remote upload reconciliation, accessibility, notifications and approval remain its responsibility.
- [ ] Keep real candidate documents, raw process output, credentials and runtime data outside Git/shared handoffs. No code, dependencies, templates or runtime artifacts are implemented by this planning task.
