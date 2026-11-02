# AUTO-01 — Native Windows startup and scheduling

Component: **AUTO-01 only**  
Status: **IMPLEMENTED & VERIFIED (AUTO-01 Native Subprocess / Scheduling Integration; Unattended Reboot-Without-Login marked PENDING physical host verification) — See docs/components/AUTO-01.md**  
Prepared: **31 October 2026 (Europe/Berlin)**  
Requirements: **R14, R17**; supporting constraints **R07, R09, R15, R16**, and **R10–R12** only for the optional generation-worker branch.  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§3–10 and gate G5.

## Objective and boundary

Make the existing application runnable on native Windows after reboot and logout, under an explicitly configured identity, with bounded scheduling, model readiness, durable recovery, safe resource access, and inspectable failures. Scheduled and manual execution must use the same CLI, application services, data root, and deployment lock.

All stories below remain deferred. This planning deliverable creates no task, service, account, credential, runtime configuration, migration, or background process. A later implementation request must select AUTO-01; production activation is a separate operational step after its verification gates pass.

AUTO-01 owns Windows launch configuration and a thin scheduling boundary. It does not own fetching, matching, synchronization, request admission, document rendering, retention policy, or their retry state machines. It must not reproduce pipeline stages in PowerShell or a second Python worker. It must not create drafting requests from matches (AUTO-02), send per-run notifications (AUTO-03), deploy summary records/Flows (SF-09), approve documents, or submit applications. Scheduling cleanup, restore, or other destructive maintenance is not included.

Scheduled processing of already-created generation requests is an optional, separately gated branch in S07. It is disabled by default. Automatic request creation remains outside AUTO-01 even if scheduled request processing is later selected.

## Repository evidence and dependencies

Repository guidance reviewed: [README.md](../../README.md), the complete blueprint, and the component handoffs below. No applicable `AGENTS.md` was found in the workspace, searched parent locations, or relevant documentation/source directories. Historical architecture documents do not add scope to the blueprint.

The following is a code inspection baseline, not new test or live-service evidence. Recheck it before implementation because prerequisite components may change.

| Dependency | Evidence inspected | Current constraint / activation gate |
|---|---|---|
| RUN-01, required | [Handoff](../components/RUN-01.md); [CLI](../../src/job_automation/orchestration/cli.py), [runner](../../src/job_automation/orchestration/runner.py), [lock](../../src/job_automation/orchestration/windows_lock.py), [path normalization](../../src/job_automation/orchestration/locking.py), [sync stage](../../src/job_automation/orchestration/sync_stage.py) | Offline/native Windows verification is recorded; live integration remains pending. Use `run start`, `run resume`, and `run show`. Search and generation acquire the OS lock before opening/migrating SQLite. Do not infer live scheduling readiness from handoff status. |
| MODEL-01, required | Blueprint component definition; [model configuration](../../src/job_automation/models/configuration.py), [provider](../../src/job_automation/models/provider.py), [model smoke harness](../../tests/manual/model_smoke.py) | **`docs/components/MODEL-01.md` is absent; no matching handoff was found. It could not be read.** Obtain a MODEL-01 handoff recording actual installation, runtime/model paths, versions/digests, loopback binding, health procedure, OS/GPU support and service-account behavior before activation. Client code and a smoke script are not runtime setup evidence. |
| OPS-01, required | [Handoff](../components/OPS-01.md); [operations CLI](../../src/job_automation/operations/cli.py), [settings](../../src/job_automation/operations/settings.py), [backup](../../src/job_automation/operations/backup.py), [restore runbook](../operations/restore.md) | Local recovery verified in the handoff; SF-04 remote drill pending. Preserve exclusive maintenance locking, explicit backup destination, capacity checks, reviewed cleanup plans and inert restored roots. A local-only backup is degraded coverage, not full recovery. |
| GEN-01, conditional | [Handoff](../components/GEN-01.md); [CLI](../../src/job_automation/generation/cli.py), [worker](../../src/job_automation/generation/worker.py) | `generation work --once` is available. The CLI constructs the worker without downstream service injection; constructor ports default to `None`. Real default composition must be completed by GEN-01 and verified before scheduled drafting. The handoff's Phase 0 heading does not override the blueprint's Phase 1 classification. |
| GEN-05, conditional | [Handoff](../components/GEN-05.md); [render settings](../../src/job_automation/generation/render_settings.py), [converter](../../src/job_automation/generation/libreoffice_converter.py), [render adapter](../../src/job_automation/generation/render_adapter.py) | Handoff records DOCX/offline verification, but LibreOffice was absent and real PDF conversion/visual verification pending. `RenderingSettings` exists; the current `AppConfig` does not expose the handoff's suggested `rendering.libreoffice_path` field. Confirm supported configuration/composition through GEN-01/05 rather than inserting an unsupported key. |
| FND-01 / DATA-01, interface coordination | [Application configuration](../../src/job_automation/configuration.py), [package dependencies](../../pyproject.toml), existing run/request repositories | `tzdata` is already a dependency. Data root must be absolute and outside the repository; config references resolve against the config file's parent. New schedule settings/records need explicit schema and migration ownership; no new C01–C15 meanings are implicit. |
| SFCLIENT-01 / SF-01 / SF-02, live access | [SFCLIENT-01 handoff](../components/SFCLIENT-01.md); [credential store](../../src/job_automation/salesforce/credentials.py) | Reuse current user-scoped Windows DPAPI credentials and OAuth gateway. Verify actual org schema, permissions, token refresh, and execution-identity access. Scheduling cannot supply missing org deployment or credentials. |
| MODEL-02, measured operating limits | Blueprint dependency context | Model choice, memory/GPU placement, cold-start time and execution limits require measured evidence; do not adopt model names in examples as selected deployment models. |
| GEN-02/03/04/06 and SF-05–08, conditional end-to-end gate | GEN-01/05 handoffs and current generation boundary | Component availability, v2 content/validation compatibility, rendering, delivery/reconciliation and candidate access must all be demonstrated before enabling generation polling. AUTO-01 does not fill missing implementations. |
| AUTO-03 / SF-09, downstream only | Blueprint ownership | Consume C15/run IDs later. Their absence does not prevent local launch diagnostics, but AUTO-01 alone cannot claim the full R17 per-run notification or G5 acceptance. |

### Concrete code gaps to resolve in the owning components

1. **CLI configuration fidelity (RUN-01):** the implemented flag is `--llm-strategy`, not the handoff example's `--strategy`. Parser defaults for assessment mode/strategy currently take precedence over corresponding run-file values. A nonexistent `--run-config` is silently ignored. The scheduler must reject missing explicit files and verify effective options; it must never silently downgrade LLM execution to rules.
2. **Path and live gateway composition (RUN-01 / SFCLIENT-01):** the runner uses a CWD-relative `config/sync.example.json` fallback. The CLI does not expose/pass `RunOptions.sync_config_path`, and the run-file `sync_config_path` is not consumed there. Live sync depends on a gateway passed through `RunOptions`; the CLI does not compose it. An enabled sync setting alone does not prove remote work happened. Resolve supported absolute configuration and real gateway wiring in the existing composition path before activation; do not compensate with a second sync implementation in AUTO-01.
3. **Resume fidelity (RUN-01):** `run resume` builds default `RunOptions`; the runner reads the saved request but resolves current profile/policy/sources and passes the options into execution. Verify, and where necessary fix in RUN-01, restoration or explicit invalidation of the original assessment mode, strategy, source selection, sync settings and input versions. Do not promise unattended LLM/RAG resume from the handoff alone.
4. **Atomic trigger correlation (AUTO-01 with RUN-01 / DATA-01):** there is no durable schedule occurrence key accepted by the current CLI. A crash after a run is committed but before a launcher records its UUID could otherwise start another run. S04 must add minimal optional trigger metadata at the existing admission boundary, under the existing lock, or remain blocked on that integration. A proposed flag/record in this document is not an existing command.
5. **Lock diagnostics (RUN-01):** current code uses `.deployment.lock` for the OS lock and `.deployment.lock.diag` for diagnostic metadata. Lock-open/permission failures are also surfaced as `LockContentionError`. S01/S05 must distinguish access failure from genuine contention through safe preflight/evidence; endless busy retries are not acceptable. Never delete either file to force takeover.
6. **Maintenance lock ordering (OPS-01):** `operations/cli.py::_load_env` calls `engine.migrate()` before `create_backup` acquires its maintenance lock. The backup service uses the shared lock, but that alone does not prove zero pre-lock mutation by the CLI. Coordinate an OPS-01 correction and test the actual CLI before claiming full maintenance/search exclusion; do not copy backup logic into the scheduler.
7. **Native interpreter availability (FND-01 / deployment):** a planning-time attempt to use `.venv\Scripts\python.exe` for document checks failed because its configured base Python interpreter was unavailable. Repair/recreate and verify the selected native environment during implementation; existing historical test results do not establish that this virtual environment currently launches. No environment repair was performed here.

These are prerequisite corrections or narrow integration work, not permission to implement unrelated components in an AUTO-01 chat. Missing corrections block the affected capability visibly.

## Proposed operational decisions

Native Windows, existing hardware, local inference, zero mandatory paid dependencies, one active worker, and deferred Phase 2 are requirements. The choices below are **proposed implementation defaults**, not confirmed user preferences. Record final values and evidence during implementation. Schedule time, actual account, installation paths and model selection remain unselected; no production time is inferred from these examples.

| Decision | Proposed behavior |
|---|---|
| Execution identity | One explicit non-administrator Windows account/SID for application execution; preferably the account owning existing DPAPI credentials if appropriate. A dedicated account is an alternative requiring credential enrollment and ACL provisioning. Never silently select SYSTEM or a different profile. Installation privileges, if needed, are separate from routine execution. |
| Logon | Password-backed batch logon, “Run whether user is logged on or not,” subject to local policy and verified `Log on as a batch job` rights. No interactive-token requirement, autologon, unlocked desktop, or login-trigger dependency. Task logon password and Salesforce tokens are separate secrets. |
| Model supervisor | Default: one native Task Scheduler boot task running an absolute `ollama.exe serve` executable, independent of login. A Windows service is an alternative only if MODEL-01 selects and verifies a maintained free service host. Do not register a plain CLI as though it implements the Service Control Manager protocol. Never run both supervisors for one endpoint. |
| Application scheduling | One bounded dispatcher task per deployment, boot-triggered and repeated at a proposed five-minute interval. Task Scheduler wakes the dispatcher; a small schedule evaluator computes due Europe/Berlin slots and invokes existing CLI commands. This separates calendar intent from host timezone settings and avoids relying on undocumented DST/missed-trigger behavior. No resident second pipeline daemon. |
| Task overlap | `MultipleInstancesPolicy = IgnoreNew` for each task, plus the existing cross-command `WindowsWorkerLock` for actual application mutation. Scheduler suppression is not a replacement for the deployment lock. Do not stop an existing worker to satisfy a new trigger. |
| Sleep / power | Do not change global power settings automatically. Record AC/battery, sleep/hibernate, wake-timer and task condition choices. Proposed wake-to-run is off until specifically selected; catch-up handles downtime. A powered-off computer cannot run a task. |
| Missed slots | Coalesce to one most-recent eligible slot per work kind, proposed maximum lateness 24 hours; record older slots/ranges as expired or coalesced. No replay of every missed interval. Startup without a due slot performs health checks only. |
| Repeated local hour | Execute a configured wall-clock slot once, at the earlier occurrence (`fold=0`); the repeated hour cannot create a second occurrence. |
| Nonexistent local time | Move a slot in the spring-forward gap to the first valid local instant after the gap, preserving its original intended-slot key. Distinct slots resolving to the same instant coalesce under the same documented rule. |
| Retry | Bounded startup and launch retries with persisted attempt count/deadline. Proposed maximum three transient attempts per occurrence, delays of 1 and 5 minutes; next eligibility still obeys the lateness window. Authentication/configuration/permission failures require repair, not repeated login attempts. Component retry budgets remain authoritative inside a CLI invocation. |
| Generation polling | Disabled. If later selected, bounded `generation work --once`, with its own cadence and maximum request/time budget. Do not schedule `--watch` by default. Select due search before generation, with a documented bounded fairness rule so neither can starve indefinitely. |

Microsoft documents that S4U has no network/encrypted-file access and that interactive-token tasks require a logged-on session. S4U is therefore unsuitable for this proposed network-and-DPAPI deployment; verify the selected password-backed context after boot. [Task logon types](https://learn.microsoft.com/en-us/windows/win32/api/taskschd/ne-taskschd-task_logon_type). DPAPI normally ties decryption to the encrypting user's logon credentials and computer; copying encrypted blobs to another account is not credential migration. [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).

Task actions support an explicit executable, arguments and working directory. Set all three; do not rely on a default CWD or PATH. [Scheduled task actions](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskaction). `IgnoreNew` suppresses another instance of that task only. [Task instance policies](https://learn.microsoft.com/en-us/windows/win32/api/taskschd/ne-taskschd-task_instances_policy). `StartWhenAvailable` is a delayed scheduling aid with documented applicability limits; it does not define the application's catch-up ledger. [StartWhenAvailable](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-startwhenavailable).

Ollama documents a standalone Windows distribution and `ollama serve` service integration; it also documents account-specific binary, model and log locations. The boot-task choice above is a project proposal requiring native verification, not a claim that the ordinary installer already provides unattended startup. [Ollama on Windows](https://docs.ollama.com/windows). Python `zoneinfo` supports IANA zones and ambiguous-time `fold`; retain the existing `tzdata` dependency on Windows and explicitly validate gap handling by UTC round trips. [Python 3.12 zoneinfo](https://docs.python.org/3.12/library/zoneinfo.html). Recheck platform documentation at implementation time.

## Inputs, outputs and ownership

Inputs: validated non-secret schedule settings; resolved deployment paths; execution SID and resource-access evidence; existing app/run/model/operations configuration; approved runtime/model installation; original run/request IDs and recovery receipts; native task definitions and task history.

Outputs: disabled, reviewable task definitions; optional service definition only if selected; identity/resource manifest; bootstrap/readiness result; durable schedule-occurrence/launch receipts; links to existing C15 summaries or generation reports; sanitized local failure records; operational runbook, rollback procedure and verification evidence.

Proposed owned files during future implementation:

- `src/job_automation/operations/scheduling/`: settings, calendar calculation, launch admission coordination, safe subprocess launch and diagnostic records only.
- `scripts/windows/` and `config/`: reviewable task-definition generation, validation, explicit install/disable/remove commands and non-secret examples. Never put passwords in XML or command arguments.
- `docs/operations/`: native startup/scheduling, identity enrollment and rollback runbook; `docs/components/AUTO-01.md`: future handoff.
- `tests/operations/` and `tests/manual/`: schedule-boundary tests and native operational drill harnesses.

Coordinate minimal CLI/admission wiring with RUN-01/GEN-01; storage migration with DATA-01; runtime readiness with MODEL-01; settings/schema changes with FND-01. Do not allocate a migration number until implementation. Preserve C15 version/counting units and existing C13/C14 contracts.

Proposed companion records, version 1.0, are internal scheduling records rather than new pipeline state domains:

| Record | Required information / invariant |
|---|---|
| Schedule definition | Stable deployment/schedule IDs; definition version/hash; enabled=false default; work kind; Europe/Berlin intent and local times/cadence; activation epoch; gap/fold/missed policies; budgets; absolute config/action paths; no secrets. Changing a definition must not replay historic slots automatically. |
| Occurrence | Unique `(deployment_id, schedule_id, definition_version, intended_local_slot)` key; intended wall time, zone, chosen UTC instant/offset/fold; due/expired/coalesced/deferred/terminal outcome; next retry, count and deadline; authoritative run ID or generation attempt ID if admitted. |
| Launch attempt | Own UUID; occurrence key; task identity/version; observed UTC start/end; sanitized effective-path/config fingerprints; bootstrap and readiness categories; child exit code; supervisor result; report reference; nullable application run ID. No invented run ID when Python never started. |

Admission must atomically bind an occurrence to the application run/attempt under the existing worker lock before business work starts. On crash or duplicate trigger, reuse that binding and the existing recovery route. Schedule metadata may select *when* a CLI command runs; only the existing runner/worker decides *how* its work resumes. No exactly-once network-delivery promise.

## Deferred implementation stories

### AUTO-01-S01 — Freeze the execution identity, paths and resource manifest

Status: **DEFERRED**. Depends on RUN-01, OPS-01, FND-01; SFCLIENT-01/SF-02 for credential access; MODEL-01 for model paths. Owns non-secret deployment configuration and identity/access runbook. Covers R14/R15/R17.

Tasks:

1. Select and record account name/SID, batch-logon mode/rights and local policy constraints. Verify account password expiry/rotation handling and noninteractive profile availability. If using a dedicated account, enroll secrets through the existing credential-store workflow under that identity; do not export plaintext secrets.
2. Define absolute Python/virtual-environment, package installation, launcher, app config, run config and working-directory paths. Use an installed package in the selected native Python environment; neither shell activation nor pytest's `pythonpath` is a deployment mechanism.
3. Resolve every referenced policy/source/sync/model/generation/operations file against its explicit base; reject missing files and repository-local runtime data. Require manual and scheduled commands to address the same canonical physical data root, including case/junction aliases.
4. Record read/execute access to code, virtual environment, models, templates and fonts; required write access to SQLite/WAL/SHM, lock/diagnostics, data, indexes, profiles, logs, staging, temporary files, credential refresh store and selected backup destination. Model runtime identity may differ only with an explicit access matrix.
5. Use local absolute storage paths for SQLite and locking. Do not depend on interactive mapped drives. If a UNC backup destination is selected, verify it with the actual account/network context; a network backup path does not move the live database onto a share.
6. Validate outbound DNS/TLS/source/Salesforce connectivity, proxy/certificate requirements and token refresh without interactive browsers. Keep secrets out of task XML, arguments, config examples, logs and source control. Restrict file/task ACLs to the account and necessary administrators.

Acceptance: from a different CWD and without an activated environment, the exact account can resolve the same approved configuration/data store and required resources. A missing config, denied directory, wrong account or inaccessible DPAPI secret causes an actionable failure before pipeline work. The recorded manifest contains secret references only. Paths such as `C:\Job Automation Prüfung\Daten` work without quoting/encoding loss.

Tests: T01, T03, T08, T12. Configuration impact: deployment manifest and ACL/task-principal specification; no change to credential format. Rollback: restore recorded ACL/task-principal configuration only for project-owned resources; keep original encrypted credentials until the replacement identity has passed verification. An account change requires re-enrollment, not decryption bypass.

### AUTO-01-S02 — Supervise model startup and bounded readiness

Status: **DEFERRED**. Depends on S01, MODEL-01 and measured MODEL-02 limits; reuses LLM-01. Owns model launch supervision, not runtime installation or inference code. Covers R07/R14/R16/R17.

Tasks:

1. Obtain the missing MODEL-01 handoff. Record the exact absolute binary, version, required GPU libraries/drivers, model directory, model IDs/digests, loopback endpoint, environment and log directory. Use `OLLAMA_MODELS`/other selected settings in the process context explicitly; do not inherit an interactive shell's environment.
2. Produce a disabled boot task for the single model supervisor, or document a verified Windows service alternative. For a service, specify exact binary/host, account, working directory, start mode, stop timeout, recovery actions, logs and uninstall procedure. A free service-host dependency requires version/support justification; it is not mandatory.
3. Specify bounded restart behavior and ownership checks. Detect an already healthy approved endpoint; detect an unrelated listener or conflicting tray/service launch without killing arbitrary processes. Do not install models or download updates automatically at boot.
4. Implement bootstrap/readiness ordering: validate paths/account; confirm intended runtime/endpoint; perform bounded API health and selected-model availability checks; confirm capability/digest expectations; then allow CLI admission. Port-open alone is insufficient. Use MODEL-01/LLM-01 interfaces for synthetic generation/embedding smoke checks, not another model client.
5. Keep expensive warm-up/inference serialized with application work using the existing locking boundary. Boot readiness may use non-inference status checks; a second scheduled health probe must not consume GPU/CPU concurrently with a manual worker. Do not hold a parent deployment lock while spawning a child that reacquires it.
6. Set a measured cold-start deadline, proposed initial ceiling 180 seconds with bounded polling/backoff. Record missing binary/model, wrong digest, access denial, unsupported GPU, memory exhaustion, timeout and loopback violations separately. A model failure leaves LLM work pending/failed visibly; no automatic rules-only or hosted-model fallback.

Acceptance: after cold boot without login, the intended runtime becomes ready under its configured identity within the measured limit, with required generation/embedding models accessible. Missing dependencies end readiness predictably and preserve actionable diagnostics. A deliberately configured rules-only search need not depend on inference readiness; the reported mode remains explicit.

Tests: T01, T04, T05, T10. Configuration impact: one model supervisor definition, explicit environment/log paths and readiness limits. Rollback: disable/remove only the project-owned supervisor, restore recorded environment/startup entries, and preserve model files; stop its process only after dependent workers drain. Re-enable a previously recorded interactive startup mechanism only if it was intentionally changed.

### AUTO-01-S03 — Package disabled native task definitions and the CLI launcher

Status: **DEFERRED**. Depends on S01/S02 and resolution of RUN-01 configuration/composition gates. Owns launch plumbing and task lifecycle. Covers R14/R17.

Tasks:

1. Generate named, versioned tasks under a project-specific task folder with collision checks, principal, boot/repetition triggers, working directory, `IgnoreNew`, enabled=false, explicit power/network conditions and execution limits. Export prior owned definitions before replacement; refuse unrelated-name collisions.
2. Keep definition generation/validation separate from registration and activation. Registration must default to disabled. Activation later requires recorded dependency and verification evidence; no installation, model pull or schema migration is hidden in a task-definition preview.
3. Implement only a thin launch boundary: validate schedule/config and readiness, select an eligible command, launch the absolute Python executable using a structured argument list, wait for the child, persist safe diagnostics and return its classified result. Use an explicit CWD and native Windows quoting; no shell-constructed untrusted job text.
4. Reuse `python -m job_automation run start ... --assessment-mode <rules|llm> --llm-strategy <json|rag> --json`, `run resume --run-id <uuid> ... --json` and `run show --run-id <uuid> ... --json`. Pass absolute `--config`, `--data-root` and, for start, `--run-config`. These are command shapes, not runnable deployment examples; paths/settings must be selected first.
5. Explicitly pass effective mode/strategy until RUN-01 configuration precedence is corrected; reject a missing run file before launch. Resolve sync paths and gateway through repaired existing composition. Do not rely on the repository CWD to make the example sync mapping appear valid.
6. Define child ownership and lifetime: launcher remains alive while its bounded child runs; graceful cancellation is preferred; a hard deadline must terminate the owned child tree before the next launch. Leave room for application retries, checkpoint writes and GEN-05 cleanup. Avoid Task Scheduler's generic restart-on-nonzero for the dispatcher; S04 owns classified launch retry decisions.

Acceptance: task export/import retains absolute action and CWD, runs without PATH/profile scripts/activation, propagates failures, and creates no duplicate task on repeated installation. Task actions invoke the existing CLI and contain no pipeline stages or credentials. Disabling the task prevents new launches and does not erase existing work.

Tests: T02, T03, T06, T11, T13. Configuration impact: disabled task XML/manifests and launcher configuration. Rollback: disable owned tasks, drain children, restore the previous task export/configuration or unregister only the new owned definitions. No database rollback is implicit.

### AUTO-01-S04 — Define Europe/Berlin slots, missed runs and durable admission

Status: **DEFERRED**. Depends on S03, RUN-01 resume/admission gates, DATA-01 and FND-01. Owns schedule semantics and companion records. Covers R14/R16/R17.

Tasks:

1. Validate IANA `Europe/Berlin` through the existing Python environment. Persist machine timestamps in UTC, alongside intended local slot, offset/fold and definition version. Use a monotonic clock for elapsed deadlines/backoff, not civil clock subtraction.
2. Implement the proposed DST rules with round-trip validation of nonexistent times. Compute calendar intent independently of the Windows display timezone. Record OS timezone and tzdata version for diagnosis; detect/report changes without replaying consumed slots. If using native calendar triggers instead of the proposed repeating wake task, explicitly map Windows timezone settings and demonstrate equivalent behavior before changing the decision.
3. Define first activation to start at its recorded activation epoch, with no historical backlog. At boot/wake, coalesce missed due slots to the latest within the lateness window, record older ranges, and never infer historical source observations for missed days.
4. Bind a due occurrence to the existing run admission transaction under `WindowsWorkerLock`. Add only the optional trigger metadata necessary to the existing CLI/runner boundary; manual CLI use remains valid without it. A caller's candidate slot is revalidated under the lock. Do not use a scheduler-only PID lock, or acquire the deployment lock in a parent and then launch a child that blocks on it.
5. Recover an admitted unfinished occurrence using its original run ID and existing `run resume`. Do not run `start` again merely because the launcher lost stdout. Verify the resume fidelity gate above. Ambiguous/invalid input versions fail visibly until the owning runner can resolve them.
6. Classify launch retry: busy defers without consuming a work attempt; retryable bootstrap failures consume bounded launch attempts; partial/interrupted work uses existing IDs and retry times; invalid config/authentication stops retries. Preserve an expired retry as inspectable unfinished work rather than deleting it. A future fresh discovery slot does not erase earlier pending work.
7. Specify forward/backward clock-jump behavior: forward jumps apply the same coalescing/lateness policy; backward jumps do not repeat committed keys. Timezone/definition edits have an effective epoch and explicit migration rule; they cannot silently reset deduplication.

Acceptance examples:

- A proposed daily 07:00 Berlin slot maps to 06:00 UTC in winter and 05:00 UTC in summer, while retaining 07:00 local intent.
- For a synthetic 02:30 slot on 28 March 2027, the gap policy admits one occurrence at 03:00 CEST (01:00 UTC), with 02:30 retained as intended time.
- For 31 October 2027 at 02:30, admit once at the first occurrence (00:30 UTC, fold=0); the second 02:30 does not create another run.
- After several offline days, at most one eligible catch-up run starts; old slots are recorded as coalesced/expired. A boot trigger and a simultaneous repetition tick bind to one logical run. A boot before the first selected slot starts no discovery run.
- Crashes before admission, after run creation and before launcher acknowledgment, and after terminal C15 persistence resume or reopen the same admitted occurrence. Exactly-once physical calls are not promised.

Tests: T07, T09, T10. Configuration impact: versioned schedule settings plus additive durable occurrence/admission records and migration coordinated with DATA-01. Rollback: disable scheduling first; retain receipts and migrations for audit/recovery, using a compatible previous application build. Never drop occurrence records to force a rerun.

### AUTO-01-S05 — Prove manual, scheduled and maintenance mutual exclusion

Status: **DEFERRED**. Depends on S03/S04, RUN-01, OPS-01; GEN-01 if S07 selected. Owns integration and verification of the existing lock. Covers R14/R16/R17.

Tasks:

1. Use `WindowsWorkerLock` and the same normalized physical root for manual search, scheduled search, generation and OPS-01 mutating maintenance. Retain OS-held byte locking and automatic release on process death. Do not replace it with stale PID timestamps or Scheduler-only exclusion.
2. Keep loser behavior: no SQLite open/migration, pipeline recovery, model inference or Salesforce work before acquiring the lock. Separate launcher diagnostics may record a busy/access failure without mutating pipeline state.
3. Handle lock contention as deferred/skipped-busy with a bounded next eligible tick; do not kill the winner, queue unbounded task instances, mark the occurrence completed, or silently start on another data root. Record repeated starvation and its remedy.
4. Verify ownership across case variants, trailing separators, junctions and spaces/umlauts. Reject configurations that point manual and scheduled commands at different stores accidentally. Explicitly qualify the unsupported case of different data roots sharing one model endpoint: the per-root lock does not serialize those; the initial deployment must remain one active store/worker.
5. Verify process-tree death/cancellation and lock release with real Windows subprocesses. Parent task termination must not leave an unnoticed active child followed by a duplicate launcher. Preserve recovery receipts and let RUN-01/GEN-01 reconcile interrupted work.

Acceptance: scheduled search overlapping manual search, the reverse ordering, duplicate scheduled triggers, generation/search and backup/search all allow at most one mutating worker. Search/generation losers report code 3/busy and perform no pipeline work; maintenance uses its own documented bounded wait/error contract with no pre-lock mutation. An ACL failure is diagnosed as access failure rather than endlessly retried contention. Maintenance and later manual recovery can acquire the lock after an actual crash without lock-file deletion.

Tests: T06, T08, T10, T14. Configuration impact: shared data-root requirement, instance policy and contention budget only; no new lock protocol. Rollback: disable scheduling and return to manual CLI use with the same lock and data root; do not remove the lock files.

### AUTO-01-S06 — Preserve actionable failure reporting before and after CLI startup

Status: **DEFERRED**. Depends on S03–S05, RUN-01 summaries and OPS-01 logging/capacity rules. Owns local launcher diagnostics; AUTO-03 owns later delivery. Covers R15/R16/R17.

Tasks:

1. Record task/launch IDs, intended slot, UTC timings, actual identity, safe configuration fingerprint, readiness result, child exit code, outcome and next action. Correlate an actual run ID to C15 or generation attempt ID to its existing report. Do not turn generated-but-unpersisted report UUIDs into evidence of an admitted run.
2. Distinguish no work due, empty successful run, skipped busy, failed bootstrap, invalid config/auth, partial run, interruption and process crash. Persist terminal status even when stdout is malformed or absent, using a launcher record rather than inventing a C15 summary.
3. Preserve current search exit meanings: 0 success; 1 failure; 2 invalid/preflight; 3 busy; 4 partial/pending; 130 interruption. Interpret generation and operations codes using their own contracts: for example generation 4 is blocked, and OPS-01 backup 1 may mean local-only coverage. Recheck actual code at implementation time.
4. Propagate child results to Task Scheduler while also retaining domain status; Scheduler completion alone does not prove successful search/sync. Store bounded sanitized stdout/stderr and safe error categories; never dump full environment, tokens, raw prompts, profile text or document contents.
5. Provide a local operator view/runbook for last expected slot, last actual launch, task Last Run Result/history, model health, durable application summary and pending work. Diagnose task-level failures where the launcher never ran: disabled task, logon failure, missing executable, policy denial. Absence of a launch receipt is not success.
6. Configure bounded log rotation with OPS-01 protections. If application data/log storage is unavailable or full, retain evidence through Windows Task Scheduler history and a provisioned fallback Windows event/log destination where available. Test fallback failure too; do not claim delivery when both paths fail. A local-only deployment cannot promise remote alerts while the computer is off.
7. Document the AUTO-03 handoff: existing C15/run identity for actual runs and separate launch-failure diagnostics for pre-run failures. No email/webhook/Flow or notification retry implementation belongs here. Success, empty, partial and failed run notification acceptance remains deferred to AUTO-03/SF-09.

Acceptance: every attempted launch has a truthful terminal or interrupted diagnosis, or an identifiable Task Scheduler failure when Python could not start. Missing runtime, credentials, network, writable disk or model produces an actionable reason. Empty success is distinguishable from “did not start.” No secret/private content appears in exported task definitions or ordinary diagnostics.

Tests: T04, T08, T10–T13. Configuration impact: diagnostic location, ACL, rotation and optional event-source provisioning; no notification channel selected. Rollback: disable task-driven reporting with tasks, preserve diagnostic history, remove only a project-owned event source if unused, and retain manual C15 inspection.

### AUTO-01-S07 — Optional bounded scheduling of existing generation requests

Status: **DEFERRED / OPTIONAL / DISABLED**. Depends on S01–S06, GEN-01/05 and the live GEN-02–06/SF-05–08 integration gates. Owns launch configuration only. Covers R14/R17 and preserves R10–R12/R15/R16.

Tasks:

1. Obtain explicit selection of scheduled request processing during later implementation/activation. Until then, omit or disable its schedule entry and leave request creation/manual processing unchanged.
2. Verify real `generation work --once --config <absolute> --data-root <same-root> --json` composition through all required stages. Use current worker polling, frozen inputs, checkpoints, recovery, validation and delivery; no separate request poller or reimplementation of admission. Do not use `--through` to disguise an incomplete production pipeline.
3. Confirm the same worker identity can access approved layouts/fonts, absolute LibreOffice console executable, writable TEMP/staging and isolated renderer profile. Reuse GEN-05's isolated `UserInstallation`, subprocess timeout/tree cleanup, PDF checks and artifact reopening. Prove conversion without a logged-on desktop and without Microsoft Word.
4. Bound each polling cycle and release the existing deployment lock between cycles. Coordinate fairness with due search and manual maintenance. Handle blocked stages, missing renderer, unavailable model, upload pending and network failures through existing worker states, preserving request IDs and artifact bytes.
5. Reboot during rendering/delivery and verify frozen inputs and saved artifacts survive. Let GEN-06 reconcile ambiguous uploads before retry. A local DOCX is not a delivered DOCX/PDF set; required PDF failure cannot silently become success. Approval remains draft until the candidate acts.

Acceptance: an already-created request survives offline time and reboot, is processed by the existing CLI under the configured identity, and reaches the correct inspectable state without duplicate logical artifacts/uploads or automatic approval. Scheduled search and generation cannot overlap. If real wiring, renderer or delivery is missing, this branch remains disabled with a named blocker; a passing search-only deployment cannot claim scheduled drafting verification.

Tests: T01, T04, T06, T10, T15. Configuration impact: optional disabled cadence/work-kind entry and explicit supported rendering settings; no automatic-drafting thresholds. Rollback: disable only generation scheduling, drain any active cycle, preserve requests/artifacts and resume manually through GEN-01. No reset-to-Pending or new request IDs as a rollback shortcut.

### AUTO-01-S08 — Reboot drill, activation evidence and rollback rehearsal

Status: **DEFERRED**. Depends on S01–S06; S07 only if selected. Owns the operational acceptance record. Covers R14/R17.

Tasks:

1. Run the matrix below with synthetic fixtures in an isolated deployment, then the required live checks against the selected existing org/source/model under an appropriate later execution authorization. Record Windows/Python/runtime/model/tzdata versions, task export hash, account SID, action/CWD, data-root identity and measured timings. Distinguish fake integrations, native subprocess checks and live checks.
2. Before later activation, take and verify an OPS-01 backup and export existing owned task/service configuration. Record actual backup destination and same-disk limits. Do not call a local-only backup a full Salesforce recovery test.
3. Enable only the selected task set for the drill, reboot fully, leave the machine at the sign-in screen, and collect boot/task/model/application timestamps later. Establish that work occurred before first interactive login, not merely that it worked after logging in to inspect results. Repeat logout/lock and sleep/wake scenarios separately.
4. Demonstrate actual model generation and embeddings needed by the selected mode, source/network access, credential decrypt/refresh, database writes and authorized Salesforce operations before login. For S07, include real DOCX/PDF rendering and accessible delivered files. GPU acceleration is claimed only if measured in that identity/session.
5. Rehearse disabling tasks during work, graceful drain, crash recovery, task export restoration and manual CLI operation on the same data root. Restore tests use inert isolated roots, never automatically registered tasks pointed at restored data.
6. Publish `docs/components/AUTO-01.md` with owned files, schema/config versions, checks/results, evidence references, pending gates, final operational decisions, activation state and rollback commands. Keep credentials and candidate contents out of the handoff.

Acceptance: reboot-without-login and all applicable overlap/resource/failure tests pass with evidence. Mark AUTO-01 implemented with pending native/live checks if only code/fakes pass; mark verified only for the explicitly demonstrated deployment capabilities. The overall Phase 2 G5 and notification/automatic-drafting acceptance stay pending their owners. No claim of readiness based only on “Run” in the Task Scheduler UI.

Tests: complete applicable matrix. Configuration impact: explicit later activation only after evidence is reviewed. Rollback: execute the procedure below and prove manual operation still works. This story file itself does not activate anything.

## Operational test matrix

All results are **PLANNED / NOT RUN for AUTO-01**. Prior handoff results are dependency evidence only. Use fixture clocks for calendar logic and an isolated Windows VM or approved maintenance window for OS clock/reboot tests; do not change the user's clock as part of story planning.

| ID | Scenario and method | Required evidence / pass condition |
|---|---|---|
| T01 | Cold boot without login; selected execution account; repeat logout separately | Task and model start before first interactive login; exact identity/path manifest; model/network/DPAPI/data access; real run receipt/C15 and authorized remote outcome. Optional generation includes real PDF and delivery. |
| T02 | Definition generation, disabled install, repeat install, foreign task-name collision | No automatic activation; stable owned definitions; exported principal/action/CWD/settings; foreign task untouched; disable prevents subsequent starts. |
| T03 | Absolute paths containing spaces and `Prüfung äöü ß`; launch from unrelated CWD, minimal PATH, unactivated shell | Same config/data/lock target and correct argument boundaries; no fallback to System32, example sync file or another profile's data. Missing explicit file fails before work. |
| T04 | Model absent, delayed, wrong digest, missing weights, port conflict, unsupported GPU and insufficient memory | Bounded readiness result; no silent model download/fallback; no duplicate runtime; no false successful LLM run. Record cold-start/resource measurements. |
| T05 | Runtime dies after readiness and during model request; repeated supervisor failures | Existing model error/pending behavior preserved; bounded runtime restarts and launch retries; no infinite boot loop or secret leakage; healthy recovery reuses durable work. |
| T06 | Manual search first/scheduled second and reverse; two scheduled launches; optional generation/search; maintenance backup/search | At most one mutating worker; search/generation loser code 3, maintenance's documented bounded contention result, and no pre-lock mutation/model/remote activity; ignored/deferred slot later handled once; child-process lifetime accounted for. |
| T07 | Berlin winter/summer, 2027 spring gap/autumn fold, boot at boundary, duplicate wake, host timezone change and clock jumps | S04 examples pass; stable intended-slot key; UTC records and local display correct; no duplicate fold execution; `tzdata` available in selected Python. |
| T08 | Wrong identity, missing DPAPI profile/key, revoked/expired token, password rotation, denied batch logon, denied lock/data/temp/backup ACL | Safe actionable diagnosis, no credentials in output; denied logon visible in Task Scheduler even with no launcher record; permission failure does not become infinite “busy.” Test credential refresh writes as well as reads. |
| T09 | Offline for several intervals/days; boot before due time; sleep/hibernate; boot and repetition overlap | Latest eligible slot only; old slots/ranges accounted for; no catch-up storm; no work before first activation; missed runs never fabricate source observations. |
| T10 | Crash before admission, after run commit/before launch acknowledgment, mid-stage, after summary/before supervisor acknowledgment; forced task timeout | Original occurrence/run ID recovered; original mode/strategy/config honored or explicit blocker; no new run on uncertain admission; released OS lock and no orphan child; existing outbox/request reconciliation used. |
| T11 | Success with jobs, empty success, partial source failure, failed pipeline, SIGINT, malformed/missing child output | Correct command-specific exit/status, preserved C15 or separate bootstrap diagnostic, pending work visible; task-level “completed” cannot hide partial failure. No AUTO-03 delivery claimed. |
| T12 | Disk full, log path denied, offline source/Salesforce, unavailable backup/share, proxy/cert mismatch | Classified failures, no credential/prompt leakage, bounded retry, fallback OS evidence where provisioned; OPS-01 capacity/backup limitations accurately recorded. |
| T13 | Activation then disable/remove, failed upgrade, task export restoration, manual CLI, isolated restore | Only owned tasks/services change; no data loss; credentials/model/artifacts retained; compatible manual operation works; restored roots remain unscheduled/inert. |
| T14 | Data-root case/trailing slash/junction aliases; stale diagnostic file after process death; lock held by another account with configured ACLs | One physical lock authority; OS release permits recovery; no forced lock deletion; access denied distinguished from contention. |
| T15 | Optional generation: missing LibreOffice, isolated profile permissions, fonts/umlauts, timeout tree cleanup, reboot at render/upload ambiguity | Real headless conversion under the scheduled identity; bounded failures and saved artifacts retained; existing version/receipt reconciliation; no duplicate logical delivery, false readiness or automatic approval. |

## Configuration, migration and rollback

There is no runtime/configuration/schema change in this planning task. Document checks confirmed eight unique story IDs and resolved local Markdown links; Windows timezone conversion confirmed the two 2027 DST example instants. The Python-based document check could not start because of the interpreter issue recorded above; PowerShell performed the document checks instead. No application tests, reboot drills or live-service checks were run for AUTO-01.

Future scheduling settings must default to disabled, with no selected production wall time or identity. Use a separately validated versioned settings file; if adding an `AppConfig` reference, update FND-01 schemas/fixtures explicitly because unknown keys are not assumed supported. JSON Windows paths require escaped backslashes; PowerShell commands use native paths and quoting, and Python uses `pathlib.Path`.

Any future occurrence/admission migration is additive, applied through DATA-01 under the existing application lock. Keep original C15/C13/C14 records readable. OPS-01 backup/restore coverage must include the new durable scheduling records and preserve their identity; restored deployments are disabled until explicitly re-bound and reconciled so they cannot race the original. Installation must not silently alter schema, migrate credentials, change model versions or rewrite unrelated Windows settings.

Later rollback sequence:

1. Disable all owned application triggers first, including optional generation and pending restart paths. Export task definitions, settings and safe diagnostic evidence. Do not indiscriminately stop every Python/Ollama process.
2. Let the active CLI finish or use its documented controlled stop. If forced termination is necessary, stop only the owned process tree, retain interrupted state and verify OS-lock release. Never delete `.deployment.lock` to take ownership.
3. Stop/disable the owned model supervisor only after dependent work has drained. Remove only tasks/services installed by AUTO-01, or restore their recorded previous definitions. Restore previous startup/environment settings only where this deployment changed them.
4. Keep SQLite, occurrence/run/request receipts, protected credentials, model files, local artifacts and logs. Do not undo a migration by dropping tables or restore an old database over newer acknowledged remote work. Use a compatible prior build or OPS-01's isolated restore/reconciliation procedure.
5. Verify manual `run show` and the applicable existing start/resume or generation CLI on the same absolute config/data root. Resolve any pending remote ambiguity through RUN-01/GEN-01/GEN-06. Restore credentials through the existing enrollment mechanism if identity changed.
6. Confirm no project task/service launches again at the next boot or interval; record what remains disabled and any manual recovery still required. A later reactivation keeps occurrence history and uses an explicit effective epoch/catch-up decision.

## Handoff checklist

- [ ] All stories remain deferred until selected; final capability scope and generation opt-in are explicit.
- [ ] MODEL-01 handoff obtained; RUN-01 CLI/config/live-gateway/resume/admission gaps resolved by their owners or listed as blockers.
- [ ] Final execution SID/logon mode, absolute paths, environment, ACLs, credential enrollment/rotation and resource matrix recorded without secrets.
- [ ] Model supervisor choice, loopback access, versions/digests, cold-start/readiness/resource bounds and crash behavior verified.
- [ ] Task definitions, enabled state, time/power/repetition settings, action/CWD and ownership exports recorded.
- [ ] Berlin DST, missed-run, definition-change, retry and occurrence identity behavior verified with fixture clocks and applicable native checks.
- [ ] Manual/scheduled/generation/maintenance overlap and process-tree recovery verified using the existing lock.
- [ ] Real reboot-before-login evidence distinguishes OS/native/live checks from fakes; optional rendering/delivery gates remain visible.
- [ ] Failure records and C15/report correlation cover bootstrap, empty, partial, failed, interrupted and suppressed work; AUTO-03/SF-09 delivery remains separately owned.
- [ ] OPS-01 backup, inert restore and rollback rehearsal documented; no automatic destructive maintenance added.
- [ ] Future component handoff states actual implemented/verified capabilities, remaining limitations and activation state; no overall G5 claim from AUTO-01 alone.
