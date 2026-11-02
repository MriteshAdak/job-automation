# Synthetic Source Registry Fixtures Catalog

This directory contains synthetic, non-sensitive fixtures for testing source registration,
validation, access review, attribution, request policy, inventory semantics, and CLI behaviors
under component **SOURCE-01**.

All domains use `.invalid`, all credentials/tokens are synthetic, and no real employer or
provider data is stored.

## Fixture Index

| Fixture File | Purpose / Scenario | Expected Outcome |
|---|---|---|
| `valid_registry.json` | Valid multi-source registry covering API, manual import, and permitted scraping. | Pass validation; sources inspectable. |
| `empty_registry.json` | Valid explicit empty registry (`sources: []`). | Pass validation; 0 sources selected. |
| `invalid_duplicate_source_key.json` | Registry containing two distinct entries with identical `source_key`. | Fail loader validation with `duplicate_source_key`. |
| `invalid_duplicate_json_key.json` | Raw JSON payload containing duplicate keys in an object. | Fail loader parse with `duplicate_json_member`. |
| `invalid_unsupported_schema.json` | Registry declaring `schema_version: "99.0"`. | Fail loader validation with `unsupported_schema_version`. |
| `invalid_secret_credentials.json` | Source declaring inline `Authorization` header and URL userinfo `user:pass@`. | Fail request policy validation with `disallowed_credential`. |
| `invalid_complete_board_filter.json` | Source claiming `complete_board` semantics while declaring search query `q=engineer`. | Fail inventory validation with `scope_contradiction`. |
| `invalid_request_policy_bounds.json` | Source with negative timeout, boolean max_attempts, and unknown typo key `timeuot`. | Fail request policy validation with `invalid_request_policy`. |
| `invalid_denied_access.json` | Source with explicit recorded access denial (`status: "denied"`). | Access review status DENIED; blocked from selection. |
| `invalid_expired_access.json` | Source whose access review has expired timestamp. | Access review status EXPIRED/DENIED; blocked from selection. |

