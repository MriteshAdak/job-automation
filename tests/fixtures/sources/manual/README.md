# Synthetic Fixtures Catalog: Manual Sources (SOURCE-02)

This directory contains synthetic test fixtures used for verifying the manual URL-plus-text and CSV import adapters (`ManualTextAdapter`, `ManualCsvAdapter`).

All identities and URLs are synthetic; URLs use the `.invalid` reserved TLD.

## Text Fixtures (`tests/fixtures/sources/manual/text/`)
- `valid_job.txt`: German HTML job posting with title, location, compensation, and qualifications.
- `empty_job.txt`: Blank/whitespace-only text file triggering `missing_posting_text`.
- `hostile_job.txt`: Inert adversarial text containing shell commands, SQL injections, `<script>`, tracking pixel `<img>`, and formula `=cmd|...` strings. Verifies text is treated strictly as data without execution.

## CSV Fixtures (`tests/fixtures/sources/manual/csv/`)
- `valid_jobs.csv`: Comma-delimited CSV with explicit posting IDs, URLs, titles, companies, descriptions, locations, and salaries.
- `valid_semicolon.csv`: Semicolon-delimited CSV demonstrating European/German export support.
- `multiline_quoted.csv`: Multi-line quoted fields tracking line numbers across record boundaries.
- `invalid_missing_columns.csv`: CSV missing required `text` column.
- `invalid_duplicate_headers.csv`: CSV with duplicate `text` column headers.
- `mixed_errors.csv`: 3 rows where row 2 contains an invalid URL, verifying row-level error isolation.
- `bom_jobs.csv`: UTF-8 with Byte Order Mark (`\xef\xbb\xbf`).

