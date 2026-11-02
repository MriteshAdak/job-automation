# INGEST-02 Normalization Test Fixtures

Test corpus for verifying cross-source equivalence, unknown preservation,
HTML cleaning, date/location/workplace/compensation normalization, and structured quarantine handoffs.

## Fixture Categories
- **`manual_text/`**: URL-plus-text HTML fixtures for Sachbearbeiter (m/w/d) and developer roles with German entities, umlauts, and paragraph/list tags.
- **`manual_csv/`**: UTF-8 BOM/CRLF CSV records with quoted multiline text, semicolon variants, and preserved exact string IDs (e.g. `0007`).
- **`nested_ats/`**: Structured/nested object mappings for title, company, locations, and pay.
- **`flat_feed/`**: Arbeitnow-shaped flat JSON items with boolean remote flags, unpromoted created_at timestamps, and list job_types.
- **`structured_board/`**: Explicit workplace enums, remote-DE / EU restrictions, employment labels, and advert language.
- **`unknowns/`**: Missing keys, nulls, blanks, empty collections, zero and false variants.
- **`text/`**: Hostile markup (scripts, style, comments), broken unclosed tags, C++, C#, SQL, PowerShell, and prompt injection strings.
- **`dates/`**: ISO offsets, Unix epoch 0, date-only/month-only precision preservation, naive times, and DST gaps/folds in Europe/Berlin.
- **`locations/`**: Berlin, Hamburg, Springfield (unknown country), Baden-Württemberg, and duplicate location sets.
- **`workplace/`**: Remote-DE, EU, worldwide, remote with absent restrictions, hybrid, boolean false, and conflicting labels.
- **`compensation/`**: German/English formatted bounds, hourly/monthly/yearly, lower/upper-only, bare numbers, ambiguous $, and weekly periods.
- **`invalid/`**: Blank titles, missing company hints, script-only descriptions, wrong types, reversed compensation bounds, and bad URLs.
- **`provenance/`**: Broken raw references, hash mismatches, and replay snapshots.
- **`mixed/`**: Mixed batch of records verifying independent failure isolation (valid neighbors survive malformed records).

