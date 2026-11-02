# SF-04 — Org Capacity and Operational Headroom

Component ID: **SF-04 / Capacity**  
Requirement References: **R09, R16**; supporting **R04, R08, R14, R15**  
Implementation: [`src/job_automation/salesforce/capacity.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/salesforce/capacity.py), [`src/job_automation/salesforce/portability_records.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/salesforce/portability_records.py), [`src/job_automation/salesforce/portability_settings.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/salesforce/portability_settings.py)

---

## 1. Capacity Architecture & Limits Mapping

SF-04 establishes authenticated, dated capacity monitoring bound to the source Salesforce organization ID and API version. It queries the Salesforce REST Limits API (`/services/data/vNN.0/limits/`) via `LimitsRequest` and maps the structured `LimitsResult`.

### 1.1 Limits Extraction and Calculation Rules

1. **Daily API Requests**:
   - Extracted from `LimitsResult.daily_api_requests_max` and `LimitsResult.daily_api_requests_remaining` (or fallback to `raw_limits["DailyApiRequests"]`).
   - Formula: `used = max - remaining` (evaluated strictly when `remaining <= max` and both are valid non-negative numbers).
2. **Data Storage (MB)**:
   - Extracted from `LimitsResult.raw_limits["DataStorageMB"]` (`Max` and `Remaining`).
   - Units are explicitly preserved in MB.
   - Formula: `used = max - remaining`.
3. **File Storage (MB)**:
   - Extracted from `LimitsResult.raw_limits["FileStorageMB"]` (`Max` and `Remaining`).
   - Formula: `used = max - remaining`.
4. **Zero-Maximum and Missing-Metric Safeguards**:
   - If `max_value <= 0`: reported as `unknown` (never divided by zero).
   - If any metric is absent (e.g. missing `FileStorageMB`): reported as `unknown` with explanatory diagnostic notes. Missing metrics **never** become healthy or unlimited.
   - If `remaining < 0` or `remaining > max`: reported as `unknown` due to inconsistency.

---

## 2. Headroom Evaluation & Operational Reserves

Operational decisions distinguish between org-level quotas and application-level safety reserves:

```
[Total Org Allocation (Max)]
  ├── Used Capacity (Max - Remaining)
  ├── Remaining Headroom
  │     ├── Warning Buffer (Effective Reserve * warning_multiplier)
  │     └── Effective Reserve (max(absolute_reserve, Max * reserve_percent / 100))
  └── Blocked Threshold (Remaining < Effective Reserve)
```

### 2.1 Default Operational Policy (`CapacityPolicySettings`)

| Resource | Absolute Reserve | Percentage Reserve | Warning Multiplier | Default Max Age |
|---|---|---|---|---|
| **Data Storage** | 5.0 MB | 10.0% | 2.0x | 1.0 hour |
| **File Storage** | 10.0 MB | 10.0% | 2.0x | 1.0 hour |
| **Daily API Requests**| 100 requests | 5.0% | 2.0x | 1.0 hour |

---

## 3. Operation-Specific Decisions

Rather than a single global boolean, `evaluate_capacity_decision` yields operation-specific decisions:

| Operation Kind | Evaluated Headroom | Cost Estimation | Failure Behavior |
|---|---|---|---|
| **`publication`** | Data Storage & Daily API Requests | `planned_records * 2048 bytes` (~2 KB/row) + API calls | Defers new record publication; preserves pending sync outbox. Does **not** delete records. |
| **`file_upload`** | File Storage & Daily API Requests | Exact artifact binary size in MB + API calls | Keeps local artifact with `upload_pending`; preserves prior versions. |
| **`export_read`** | Daily API Requests only | Budgeted read calls (pages) | Proceed even if data storage is full (read-only operations do not consume storage). |

---

## 4. Observed Developer Edition Org Baseline

Based on Developer Edition platform specifications and local environment configuration:

- **Target Org Binding**: `dev-main` (`https://mritesh-adak-dev-ed.develop.my.salesforce.com`)
- **API Version**: `60.0`
- **Standard Allocations**:
  - `DailyApiRequests`: 15,000 requests / 24 hours
  - `DataStorageMB`: 5 MB standard allocation
  - `FileStorageMB`: 20 MB standard allocation
- **Live Measurement Status**: **PENDING (Target Org Session Authorization)**. Offline gateway and synthetic fixtures verified; live REST query ready to run upon interactive operator login.

---

## 5. Non-Blocking Remote Outage Behavior

When Salesforce is unreachable, credentials expire, or a network timeout occurs:
- The capacity observation records `status = "unknown"` with actionable error details.
- Local operations and read-only inspection (e.g. `ops capacity`) remain fully functional and report local volume health without marking local disks `BLOCKED`.
- Exhausted API quotas enforce backoff delays (`recheck_delay_seconds = 300`) to prevent unbounded polling loops.

