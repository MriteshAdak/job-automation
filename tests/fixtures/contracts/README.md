# Synthetic Contract Fixtures (C01–C15)

This directory contains versioned synthetic fixtures for all contracts defined by FND-01.

All fixtures are strictly synthetic:
- UUIDs are synthetic markers (e.g. `11111111-1111-4111-8111-111111111111`).
- Employer names, job descriptions, candidate facts, and credentials are fictitious.
- No live secrets, candidate personal facts, or API tokens are present.

## Directory Structure

```text
tests/fixtures/contracts/
  C01/  # ProfileSnapshot (valid.json, invalid.json)
  C02/  # SearchPolicy (valid.json, invalid.json)
  C03/  # SourceConfig (valid.json, invalid.json)
  C04/  # FetchManifest (valid.json, invalid.json)
  C05/  # RawPosting & SourceJobDraft (valid.json, invalid.json)
  C06/  # NormalizedPosting (valid.json, invalid.json)
  C07/  # CanonicalJob & PostingRevision (valid.json, invalid.json)
  C08/  # EvidenceReference (valid.json, invalid.json)
  C09/  # ContextBundle (valid.json, invalid.json)
  C10/  # ModelCall & ModelResult (valid.json, invalid.json)
  C11/  # Assessment (valid.json, invalid.json)
  C12/  # SyncOperation (valid.json, invalid.json)
  C13/  # GenerationRequest (valid.json, invalid.json)
  C14/  # DraftDocument & Artifact (valid.json, invalid.json)
  C15/  # RunSummary (valid.json, invalid.json)
```

## Regeneration

Fixtures can be regenerated or audited using:

```powershell
.\.venv\Scripts\python.exe tests/fixtures/contracts/generate_fixtures.py
```

