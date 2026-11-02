# MATCH-02 Test Fixtures and Synthetic Corpus

This directory contains synthetic test fixtures supporting model-assisted relevance assessment (MATCH-02) across offline unit, contract, boundary, integration, and manual smoke test suites.

## Privacy and Synthetic Data Guarantee

All candidate profiles, job postings, company hints, and requirement passages in these fixtures are entirely synthetic. No production candidate data, credentials, or proprietary assets are included.

## Fixture Catalog

| Category | Fixture / Test Area | Description | Related Stories / Invariants |
|---|---|---|---|
| `requirements` | Deterministic passages | Synthetic German and English job descriptions testing exact Unicode offsets, obligation (`REQUIRED`, `PREFERRED`), negation (`Keine Zertifizierung erforderlich`), and alternatives (`Bachelor oder gleichwertig`). | MATCH-02-S02 (M02-02, M02-03) |
| `proposals` | Structured model outputs | Valid `AssessmentProposal` payloads conforming to strict schema with 0-100 scores and summary syntheses. | MATCH-02-S04, S05 (M02-01, M02-06) |
| `citations` | Citation validity | Test scenarios covering valid references, unknown requirement IDs, duplicate findings, unselected fact citations, and out-of-bounds spans. | MATCH-02-S04 (M02-06, M02-10) |
| `injections` | Security prompt boundaries | Malicious job text containing instruction override attempts, commands (`curl`, `rm`), and private token exfiltration attempts verifying untrusted fencing. | MATCH-02-S05 (M02-09) |
| `precedence` | Deterministic authority | Baseline hard-failure, policy-rejection (`on_missing='fail'`), and factual unknown combinations paired with high model scores proving deterministic precedence. | MATCH-02-S06 (M02-08) |
| `failures` | Error envelopes | Model connection refusal (503), timeout, and context overflow fixtures verifying pending `AssessmentRunResult` envelopes and retryability flags. | MATCH-02-S07 (M02-07, M02-13) |

