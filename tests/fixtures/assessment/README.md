# Assessment Test Fixtures Catalog (MATCH-01)

This directory contains synthetic, reproducible C06 `NormalizedPosting` JSON fixtures for testing deterministic job assessment (MATCH-01).

## Fixtures

| File | Scenario | Expected Disposition (against `valid_tech.json`) | Key Verification Focus |
|---|---|---|---|
| `eligible_posting.json` | Remote Python role in Berlin matching all hard criteria and keywords | `ELIGIBLE` (when `min_score_threshold` is not set) | Full pass path, remote restrictions matching candidate work authorization, compensation in EUR/yearly satisfying criteria. |
| `hard_fail_posting.json` | Mandatory onsite job in Munich | `REJECTED` | Hard criterion failure: policy requires workplace `in: ["remote", "hybrid"]`, posting specifies `onsite`. |
| `missing_compensation_posting.json` | Fast-growing startup omitting compensation details | `REVIEW` (or `ELIGIBLE` if waived) | Missing information precedence (D03): when compensation is absent and unstated, routes to `REVIEW` with identified unknown. Passes if explicitly waived (`on_missing: pass`). |
| `excluded_employer_posting.json` | Role at "Euro Gambling Entertainment AG" | `REJECTED` | Definitive employer exclusion: company name contains excluded term `"Gambling"`. |

## Usage

Load via Pydantic model validation:

```python
from pathlib import Path
from job_automation.contracts.postings import NormalizedPosting

posting = NormalizedPosting.model_validate_json(
    Path("tests/fixtures/assessment/eligible_posting.json").read_text(encoding="utf-8")
)
```

