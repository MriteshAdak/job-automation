# Component Handoff: AUTO-01 — Native Windows Scheduling, Startup, and Model Supervision

Component ID: **AUTO-01**  
Status: **VERIFIED (Subprocess, Native Integration, Overlap Contention, and Manual Smoke Drills) — Unattended Reboot-Without-Login marked PENDING physical host verification**  
Phase: **Phase 2 (Automation & Supervision)**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), §§3–10, Phase 2, gate G5; [docs/stories/AUTO-01.md](../stories/AUTO-01.md)  
Prerequisite Handoffs:
- [RUN-01](RUN-01.md) (**VERIFIED**)
- [OPS-01](OPS-01.md) (**VERIFIED**)
- [DATA-01](DATA-01.md) (**VERIFIED**)
- [MODEL-01 / LLM-01](LLM-01.md) (**VERIFIED**)  
Date Completed: 31 October 2026  
Direct Covered Requirements: [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14) (Native Windows runtime, paths, timezone), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15) (Local model supervision & readiness), [R17](../../IMPLEMENTATION_BLUEPRINT.md#r17) (Civil time, DST gap/fold resolution, missed-run coalescing), [R02](../../IMPLEMENTATION_BLUEPRINT.md#r02) (Automated search trigger correlation)  

---

## 1. Executive Summary & Component Scope

`AUTO-01` delivers native Windows automated scheduling and startup integration around existing CLI commands (`run start`, `run resume`, `run show`, and optionally `generation work --once`).

It provides a bounded Windows Task Scheduler 2.0 architecture, explicit execution identity and non-secret path manifests, strict `Europe/Berlin` civil time calculations with automatic DST anomaly resolution, Ollama model supervisor readiness probing, missed-run coalescing, and single-worker deployment locking (`WindowsWorkerLock`).

### Core Capabilities
1. **Bounded Task Scheduler Architecture**:
   - Generates inspectable, reviewable Windows Task Scheduler 2.0 XML definitions (`JobAutomation_Dispatcher.xml` and `JobAutomation_ModelSupervisor.xml`).
   - Strict `MultipleInstancesPolicy = IgnoreNew` prevents overlapping dispatcher runs.
   - All tasks are registered in a **disabled state by default** (`Enabled = false`).
   - PowerShell scripts (`install_tasks.ps1`, `uninstall_tasks.ps1`, `export_tasks.ps1`, `status_tasks.ps1`) manage registration safely without global host state mutation.
2. **Europe/Berlin Civil Time Engine (`CalendarCalculator`)**:
   - Calculates target slots (default `07:00` Europe/Berlin) against civil calendar dates.
   - **Spring forward 1-hour gap resolution**: When 02:30 does not exist in local civil time (e.g., 2027-03-28), the engine detects the gap and advances execution to the first valid instant (03:00 CEST = 01:00 UTC) while preserving the intended slot key (`2027-03-28T02:30:00 Europe/Berlin`).
   - **Autumn fold disambiguation**: When 02:30 occurs twice during the 03:00 -> 02:00 fold (e.g., 2027-10-31), the engine selects `fold=0` (earlier occurrence, 00:30 UTC) and ignores the second occurrence, avoiding duplicate execution.
   - **Missed-run coalescing**:
     - Missed slots older than 24 hours (`max_lateness_hours`) are marked `EXPIRED`.
     - Multiple missed slots within 24 hours are coalesced: older slots are recorded as `COALESCED`, and only the single latest eligible slot is admitted as `DUE`.
     - Zero backfill prior to schedule `activation_epoch`.
3. **Model Supervisor & Loopback Readiness Probing (`ReadinessProbe`)**:
   - Before launching an LLM-assisted search run, probes the loopback service (`http://127.0.0.1:11434/api/tags`) via HTTP GET.
   - Rejects non-loopback endpoints to prevent external SSRF or unauthenticated exposure.
   - Verifies the configured model identifier (e.g., `qwen3:4b`) is present among installed tags.
   - If unreachable or model missing: does NOT launch child pipeline, records `LaunchAttemptRecord` with `BootstrapCategory.RUNTIME_OFFLINE` or `MODEL_MISSING`, updates occurrence to `FAILED`, increments retry counter, and exits with code 2.
4. **Process Isolation & Subprocess Launcher (`SubprocessLauncher`)**:
   - Spawns subprocesses using absolute `python.exe` binary path.
   - Enforces timeout management (`ExecutionTimeLimit = PT2H` in task, default 3600s in dispatcher) with clean process-tree termination.
   - Captures up to 64KB of stdout/stderr tail for durable failure diagnostics.
   - Redacts tokens, URLs with passwords, database connection strings, and credentials (`[REDACTED]`).
5. **Interrupted Work Recovery**:
   - If an occurrence is in `IN_PROGRESS` or `PARTIAL` with an existing `admitted_run_id`, the dispatcher automatically invokes `run resume --run-id <admitted_run_id>`.
6. **Cross-Component Deployment Lock (`WindowsWorkerLock`)**:
   - All manual runs (`run start`), scheduled runs (`ops schedule dispatch`), and maintenance operations (`ops backup create`) compete for the shared deployment lock at `<data_root>/.deployment.lock`.
   - Contention produces exit code 3 (`LOCK_BUSY`), transitions occurrence to `SKIPPED_BUSY`, and schedules exponential backoff retry without corrupting runtime state.
   - Lock permission/access failures produce exit code 2 (unrecoverable preflight).

### Scope Boundaries & Non-Goals
- **Pipeline Logic**: Owned by `RUN-01`; dispatcher only launches existing CLI commands.
- **Application Request Creation**: Owned by `AUTO-02`; AUTO-01 does not author drafting requests.
- **Run Notifications**: Owned by `AUTO-03`; AUTO-01 persists C15 summaries and launch attempt audit records in SQLite, but does not send push notifications.
- **Salesforce Org Metadata**: Gated under SF-01/SF-02; unaffected by AUTO-01.
- **Generation Polling**: S07 generation polling (`generation work --once`) is disabled by default in baseline configuration.

---

## 2. Traceability & Contracts Implemented

### 2.1 Contracts Implemented (`job_automation.operations.scheduling.records`)

| Contract Record | Version | Status | Purpose |
|---|---|---|---|
| `ScheduleDefinition` | 1.0 | **VERIFIED** | Active schedule configuration, target times, timezone, retry policy, and activation epoch. |
| `ScheduleOccurrence` | 1.0 | **VERIFIED** | Individual scheduled slot lifecycle (DUE, IN_PROGRESS, SUCCEEDED, FAILED, SKIPPED_BUSY, COALESCED, EXPIRED). |
| `LaunchAttemptRecord` | 1.0 | **VERIFIED** | Point-in-time audit record capturing child PID, exit code, bootstrap status, and sanitized stderr tail. |
| `IdentityResourceManifest` | 1.0 | **VERIFIED** | Non-secret manifest of account, logon type, absolute binaries, data root, and ACL requirements. |
| `ReadinessProbeResult` | 1.0 | **VERIFIED** | Loopback probe outcome, bootstrap category, latency, and installed model tags. |
| `SchedulingSettings` | 1.0 | **VERIFIED** | External scheduling settings schema (`schemas/v1/scheduling_settings.schema.json`). |
| `DispatchReport` | 1.0 | **VERIFIED** | Dispatch execution summary, exit code, occurrence ID, and run ID correlation. |

JSON schemas for operational records have been validated in `schemas/v1/`.

### 2.2 Storage Migration 016 (`MIGRATION_016_SCHEDULING_OCCURRENCES_AND_LAUNCHES`)

Registered in `ALL_MIGRATIONS` with checksum verification:
- `ops_schedule_definitions`: Primary deployment scheduling configurations with versioning and master enabled toggle.
- `ops_schedule_occurrences`: Bounded occurrence ledger indexed by `(deployment_id, schedule_id, intended_utc_instant)`.
- `ops_launch_attempts`: Detailed launch execution audit log indexed by `occurrence_id` and `(deployment_id, started_at)`.

---

## 3. Deployed Configuration & Path Architecture

### 3.1 Runtime Paths and Non-Secret Manifest
Inspection via `python -m job_automation ops schedule manifest --json`:
- **Account Name**: Current Windows interactive user (e.g. `mrite`)
- **Logon Type**: `Password` (Windows Batch Logon for unattended execution)
- **Python Binary**: `C:\Users\mrite\Projects\job-search\.venv\Scripts\python.exe`
- **Application Root**: `C:\Users\mrite\Projects\job-search`
- **Data Root**: `C:\Users\mrite\AppData\Local\JobAutomation`
- **Lock Target**: `C:\Users\mrite\AppData\Local\JobAutomation\.deployment.lock`
- **Model Loopback URL**: `http://127.0.0.1:11434`
- **Ollama Binary**: `C:\Users\mrite\AppData\Local\Programs\Ollama\ollama.exe`

### 3.2 ACL & Access Requirements Matrix
- `<data_root>`: Read / Write / Delete (SQLite database, WAL, shm, artifacts, logs).
- `<data_root>/.deployment.lock`: Byte-range locking (Read / Write).
- `<venv_dir>`: Read / Execute (Python interpreter and site-packages).
- `<repo_root>`: Read / Execute (Application modules and configuration).

### 3.3 Task Scheduler XML Definitions
Generated via `python -m job_automation ops schedule export-tasks --output-dir config/tasks`:
- `JobAutomation_Dispatcher.xml`:
  - Trigger: BootTrigger with 1-minute delay, repeating every 5 minutes (`PT5M`).
  - Action: Runs `python.exe -m job_automation ops schedule dispatch --data-root "<data_root>"`.
  - Settings: `MultipleInstancesPolicy = IgnoreNew`, `ExecutionTimeLimit = PT2H`, `Enabled = false`.
- `JobAutomation_ModelSupervisor.xml`:
  - Trigger: BootTrigger with 30-second delay.
  - Action: Runs `ollama.exe serve`.
  - Settings: `RestartOnFailure = PT1M` (3 attempts), `Enabled = false`.

### 3.4 PowerShell Management Scripts
Located in `scripts/windows/`:
- `install_tasks.ps1`: Registers tasks in disabled state from XML definitions.
- `uninstall_tasks.ps1`: Safely unregisters owned tasks without touching foreign tasks.
- `export_tasks.ps1`: Exports live task definitions for auditing.
- `status_tasks.ps1`: Displays Task Scheduler operational state and last run results.

---

## 4. Verification Evidence

### 4.1 Test Matrix Coverage (AUTO-01-T01 through AUTO-01-T15)

| Test ID | Description | Suite | Result |
|---|---|---|---|
| **AUTO-01-T01** | Nominal scheduled dispatch and CLI execution | `test_scheduling_dispatcher.py` | **PASSED** |
| **AUTO-01-T02** | Task XML generation, schema compliance, disabled default | `test_scheduling_cli.py`, `scheduling_smoke.py` | **PASSED** |
| **AUTO-01-T03** | PowerShell install/uninstall syntax and XML validity | `test_scheduling_cli.py` | **PASSED** |
| **AUTO-01-T04** | Idle dispatch when no slots are due (code 0) | `test_scheduling_dispatcher.py` | **PASSED** |
| **AUTO-01-T05** | Master schedule toggle enable/disable behavior | `test_scheduling_cli.py` | **PASSED** |
| **AUTO-01-T06** | Manual vs scheduled overlap exclusion (code 3, SKIPPED_BUSY) | `test_scheduling_overlap.py` | **PASSED** |
| **AUTO-01-T07** | Interrupted run recovery (`run resume`) | `test_scheduling_dispatcher.py` | **PASSED** |
| **AUTO-01-T08** | Task Scheduler multiple instances policy (IgnoreNew) | `test_scheduling_overlap.py`, XML audit | **PASSED** |
| **AUTO-01-T09** | Model readiness probe failure (LLM mode, code 2) | `test_scheduling_dispatcher.py` | **PASSED** |
| **AUTO-01-T10** | Max retries exceeded marks occurrence terminal | `test_scheduling_dispatcher.py` | **PASSED** |
| **AUTO-01-T11** | Subprocess output tail capture and secret redaction | `test_scheduling_launcher.py` | **PASSED** |
| **AUTO-01-T12** | Missed-run coalescing (<24h coalesced, >24h expired) | `test_scheduling_calendar.py` | **PASSED** |
| **AUTO-01-T13** | Civil time DST gap/fold resolution (Europe/Berlin) | `test_scheduling_calendar.py` | **PASSED** |
| **AUTO-01-T14** | Scheduled search vs maintenance backup exclusion | `test_scheduling_overlap.py` | **PASSED** |
| **AUTO-01-T15** | Non-secret execution identity and path manifest | `test_scheduling_cli.py`, `scheduling_smoke.py` | **PASSED** |

### 4.2 Automated Test Execution Summary
- `tests/operations/test_scheduling_calendar.py`: 7 passed
- `tests/operations/test_scheduling_readiness.py`: 6 passed
- `tests/operations/test_scheduling_launcher.py`: 5 passed
- `tests/operations/test_scheduling_cli.py`: 7 passed
- `tests/operations/test_scheduling_overlap.py`: 4 passed
- `tests/operations/test_scheduling_dispatcher.py`: 5 passed
- Combined operations & orchestration test suite: **155 passed**
- Manual smoke harness (`tests/manual/scheduling_smoke.py`): **PASSED**

---

## 5. Rollback Steps

If scheduling operations must be rolled back or decommissioned:

1. **Disable Active Schedules in Database**:
   ```powershell
   python -m job_automation ops schedule disable
   ```
2. **Unregister Windows Scheduled Tasks**:
   Execute the uninstallation PowerShell script as the executing user:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/windows/uninstall_tasks.ps1
   ```
   This unregisters only `JobAutomation_Dispatcher` and `JobAutomation_ModelSupervisor`.
3. **Data Preservation**:
   Rollback does NOT touch or delete the runtime data root, SQLite database, artifacts, or backup sets.
   Manual runs (`run start`, `run resume`, `run show`) remain completely functional.

---

## 6. Operational Limitations

1. **Unattended Reboot Verification Status**:
   - In accordance with safety rules, unattended cold reboot-without-login has **NOT** been simulated on this live host to prevent disruption to interactive sessions.
   - **Status**: Marked **PENDING physical host verification drill**.
   - Running tasks without user login on Windows requires:
     - Account configured with `SeBatchLogonRight` ("Log on as a batch job" user right in Local Security Policy).
     - Account credentials supplied during `schtasks /create` or entered when enabling the task in Task Scheduler.
2. **Model Service Dependency**:
   - In `--assessment-mode llm`, the dispatcher requires Ollama running on loopback (`http://127.0.0.1:11434`) with the target model pulled.
   - If Ollama is offline or unready, the dispatcher records `BOOTSTRAP_FAILED` and exits cleanly with code 2 without starting child pipeline runs.
3. **Single-Worker Concurrency Limit**:
   - Only one pipeline worker (manual, scheduled, or maintenance) can execute concurrently per `data_root`.
   - Concurrent invocations yield exit code 3 (`LOCK_BUSY`) and will automatically retry at the next scheduled interval.

