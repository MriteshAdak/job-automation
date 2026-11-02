# Arbeitnow Adapter — Synthetic Fixture Catalog

Fixture root: `tests/fixtures/sources/arbeitnow/`  
Reviewed: 2026-10-28 UTC  
Component: SOURCE-03-arbeitnow  
Status: Synthetic / defensive — **not live captures**

All fixtures use synthetic employer names, synthetic roles, and `.arbeitnow.com`-shaped
URLs that route through the real documented host but must **never** be fetched by test
code.  Tests inject a fake HTTP transport; real network calls are guarded against.

Do **not** commit real job descriptions, copied Postman response bodies, or live API
captures.  Hash values in tests are computed from fixture bytes at test time.

## Fixture Groups

| File | Evidence basis | Expected outcome | Stories |
|---|---|---|---|
| `page_1.json` | E2-shaped envelope; 2 jobs; `links.next` page 2 | Two RawPostings, continuation_out page 2, not exhausted | S02–S06 |
| `page_2.json` | 1 job; short page; `links.next` page 3 | One RawPosting, continuation_out page 3 | S03/S06 |
| `page_terminal.json` | 1 job; `links.next=null` | One RawPosting, exhausted=True | S03/S06 |
| `empty_terminal.json` | Empty `data`; `links.next=null` | Zero items, exhausted=True | S03/S06 |
| `empty_with_next.json` | Empty `data`; `links.next` present | Zero items, continuation_out present, not exhausted | S03 |
| `missing_fields.json` | Records with absent/null fields | Mixed: some drafts with warnings, some blocking errors | S04/S05 |
| `wrong_types.json` | Records with wrong field types | Blocking errors for bad-type fields; valid neighbours preserved | S04/S05 |
| `unknown_fields.json` | Records with extra unknown fields | Preserved in original_fields; no extraction | S05 |
| `bad_envelope.json` | Valid JSON but no `data` key | page_error VALIDATION, no items | S02/S06 |
| `duplicate_slug.json` | Two records with the same slug | Same source_key twice; both captured; no deduplication | S04/S06 |
| `timestamps.json` | Various `created_at` values | Valid int preserved; null→None; bad type→blocking issue | S05 |

## Content-hash generation

Fixture JSON files are read as UTF-8.  SHA-256 hashes are computed from the exact
bytes returned by the (fake) transport — i.e., the raw response body bytes.
Derived envelope hashes are computed from the serialised envelope bytes.

Neither hash is stored in fixtures; they are computed at test time to avoid stale
golden values after formatting changes.

## Synthetic data conventions

- Employer names: German-style synthetic names (Küche & Co GmbH, Tech Startup AG, etc.)
- URLs: use the real documented host pattern `www.arbeitnow.com/view/<slug>` for
  listing URLs (data field only); the API endpoint is `www.arbeitnow.com/api/job-board-api`
- Descriptions: minimal synthetic HTML (`<p>...</p>`)
- Slugs: lowercase, hyphen-separated, numeric suffix e.g. `role-company-NNNN`
- Tags and job_types: representative German/English values

## Live capture notes

Live captures are NOT stored here.  If S07 smoke verification succeeds, a brief
summary is recorded in `docs/components/SOURCE-03-arbeitnow.md` without committing
raw API bodies.

