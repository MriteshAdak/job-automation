# Synthetic Profile Fixtures (PROFILE-01)

These fixtures provide test data for verifying candidate profile intake, version creation,
correction retention, permission restrictions, and exact historical C08 citation resolution.

## Confidentiality & Synthetic Data Invariant

**NO REAL CANDIDATE DATA IS CONTAINED IN THESE FIXTURES.**
All names, dates, employers, claims, metrics, and identifiers are purely synthetic. Real candidate
facts, CVs, and documents must live strictly outside version control beneath `$env:LOCALAPPDATA\JobAutomation\profiles`.

## Fixture Catalog

1. `synthetic_draft_v1.json`:
   - Baseline unapproved candidate draft containing employment fact `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa`
     and child project fact `bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb`.
   - Used to verify initial draft parsing, digest calculation, and V1 publication.

2. `synthetic_draft_v2_correction.json`:
   - Follow-up draft based on `v1` demonstrating:
     - Fact `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` retains its stable UUID while updating headline and claims.
     - Fact `bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb` restricts `allowed_uses: []` (private).
     - New certification fact `cccccccc-cccc-4ccc-8ccc-cccccccccccc` added.
     - Target locations and country eligibility expanded.
   - Used to verify multi-version progression, immutability of `v1`, and C08 historical lookup.

