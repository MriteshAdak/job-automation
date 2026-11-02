# INGEST-01 Test Fixtures

Catalog of synthetic fixtures, pages, and manifests used for INGEST-01 fetch controller verification.

## Contents
- **`raw/`**: Synthetic exact-byte raw payloads, JSON responses, error bodies, HTML, BOM, and CRLF samples used to verify `DurableRawCaptureSink` exact-byte preservation without loss or decoding alteration.
- **`manifests/`**: Golden C04 `FetchManifest` examples testing complete inventory, partial traversal, bounded caps, and failed executions.
- **`pages/`**: Multi-page scripted scenarios for `ScriptedPaginatedFakeAdapter` verifying pagination traversal, cycle detection, resumption, and error isolation.

