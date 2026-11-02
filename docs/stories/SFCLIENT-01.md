# SFCLIENT-01 — Salesforce authentication and gateway

Status: **PLANNED — stories only**  
Date: **29 October 2026**  
Phase: **0 / P0**  
Requirements: **R08, R15, R16**; native Windows constraint **R14**  
Direct dependencies: **FND-01, SF-02**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§4–6 and §§8–10.

Implement authenticated outbound access to the existing Salesforce Developer Org through typed operations. Consume the OAuth flow, execution identity and permissions established by SF-02. Own HTTP access, configured API version, credential/token lifecycle, safe diagnostics and bounded recovery. Do not implement publication decisions, domain field mapping or durable outbox processing.

## Repository evidence and prerequisite status

Read before planning: the blueprint, [README](../../README.md), [FND-01 handoff](../components/FND-01.md), current contracts/configuration/CLI, foundation gateway fake and interface tests, schema exporter, dependency declarations, and the existing model transport/port conventions. No applicable `AGENTS.md` was found in the repository, scoped subdirectories or ancestor locations checked. The README makes the blueprint and subsequent handoffs authoritative over historical plans.

| Evidence | Consequence for implementation |
|---|---|
| FND-01 is recorded VERIFIED on native Windows, with Python 3.12.10 and version 1.0 contracts. | Reuse its models, safe errors, config loader and schema discipline. Historical foundation results do not verify this component. Current `pyproject.toml` uses dependency ranges; record actual tested versions rather than calling those ranges exact pins. |
| [SalesforceGateway](../../src/job_automation/contracts/interfaces.py) exposes only `execute_sync(SyncOperation) -> tuple[str \| None, ClassifiedError \| None]`. | This is a domain sync boundary, not a sufficient transport interface for reads, API metadata, typed acknowledgments or replay decisions. S01 explicitly adds a versioned transport boundary while preserving legacy consumers. |
| [C12](../../src/job_automation/contracts/sync.py) carries `SyncPayload`, sequencing/fingerprint fields, attempt limits and outbox state. | SFCLIENT-01 must not translate `SyncPayload`, update C12 state/counts, order publications or persist remote mappings. These remain SYNC-01 responsibilities. |
| [Error contracts](../../src/job_automation/contracts/errors.py) already distinguish authentication, permission, rate limit, transient network/service, capacity, validation and unsupported input. | Reuse these categories. Their default `recoverable` flag is category-based, so it cannot alone authorize replay of a particular write or token exchange. |
| [AppConfig](../../src/job_automation/configuration.py) has no Salesforce settings; [example config](../../config/app.example.json) has no org/auth/API-version values. | Add optional non-secret configuration without making unrelated commands require Salesforce. Runtime data remains outside the repository. |
| `src/job_automation/salesforce/` is absent. [FakeSalesforceGateway](../../tests/fakes/fake_services.py) returns a fixed ID or authentication error. | There is no production Salesforce client to extend. The foundation fake proves interface shape only. Introduce a scripted HTTP transport and test the real gateway against it. |
| No SF-02 handoff was found under `docs/`; no SF-00/SF-01 handoff or org metadata package was found in the inspected repository. | **The selected OAuth flow, granted access and actual org configuration are unavailable prerequisites.** This is not evidence that the user's org lacks those assets. Do not invent them or claim SF-02 was reviewed successfully. |

### Required SF-02 input, before production authentication and live checks

Obtain the existing SF-02 handoff or its completed owner-supplied configuration record. It must identify the existing org/environment and approved HTTPS authorization/API origins; configured application/client identity; exact OAuth grant; approved user/run identity; scopes and object/field access; secret/key/token reference mechanism on Windows; acquisition/renewal rules; expiry, rotation and revocation policies; and any callback, audience or certificate requirements applicable to that grant. Record references and non-secret metadata only.

The handoff must also reference SF-01's resolved object names and unique External ID fields for authorized record operations. Confirm the API version to pin against the actual org and intended operations. Client API-version selection belongs here; org assets and permissions do not. Do not treat `Company__c` or `Job__c` blueprint defaults as verified org metadata.

Absent values produce actionable `missing_configuration` failures, before sending credentials or data. S01/S02 and fake-based work may proceed with explicitly synthetic capabilities. S03's production grant adapter and live acceptance remain pending until SF-02 supplies the selected flow. No alternative flow, new External Client App/Connected App, certificate deployment, scope expansion, permission set, paid integration seat or replacement org is part of these stories.

## Ownership and proposed contracts

Mandatory requirements come from the request and blueprint. The following interface names, record shapes, file names and numerical limits are **proposed implementation choices**, to freeze in S01/S02; they are not facts about the org.

SFCLIENT-01 owns `src/job_automation/salesforce/` authentication, configuration, transport, operations, errors and diagnostics. SYNC-01 later owns mapping/outbox modules in the same package. Salesforce metadata remains with SF-00/01/02. GEN-01 owns request workflow, GEN-06 owns file delivery/reconciliation, and RUN-01 owns application scheduling/locking. No Files upload, generic create/delete, Composite/Bulk API, metadata deployment or arbitrary raw-HTTP escape hatch is required here.

### Public boundary and compatibility

Add `SalesforceGatewayV2` with explicitly typed methods and request/result records. Keep the existing `SalesforceGateway.execute_sync`, C12, foundation fake and renderer signatures intact. Mark their domain-sync role in documentation; do not put a temporary job-field mapper in the new client. SYNC-01 will compose its mapper with V2 and can implement the legacy `execute_sync` facade. Future delivery consumers adopt V2 or a later narrow extension through their owning component. No claim that V2 alone conforms to the legacy protocol.

| Method / request | Inputs | Output |
|---|---|---|
| `check_connection(ConnectionCheckRequest)` | Expected org/user identity and configured API version; explicit opt-in to network checks | Typed identity/version capability evidence using only SF-02-approved endpoints, or a classified failure; never a grant expansion |
| `get_limits(LimitsRequest)` | Call ID and call budget | Typed named limit entries, nullable observed usage metadata; no assumed edition allowances |
| `describe_object(DescribeObjectRequest)` | Validated caller-selected API object name | Typed object/field capabilities needed for access and External ID checks; no schema deployment |
| `get_record(GetRecordRequest)` | Object, exactly one record ID or External ID selector, explicit field selection | Record envelope with validated ID and bounded JSON field values, or classified failure; not-found is explicit |
| `query_page(QueryPageRequest)` | Caller-built SOQL for the first page, or an opaque continuation bound to this org/version; never both | One typed page with records, `done`, total size and optional continuation; no hidden unbounded pagination |
| `upsert_by_external_id(UpsertRequest)` | Object, nonempty stable External ID field/value, caller-mapped field values and replay policy | Typed acknowledgment: target identity, returned remote ID, created/updated evidence and UTC acknowledgment time, or classified failure |
| `update_record(UpdateRequest)` | Object, record ID and explicit field patch | Typed acknowledgment for that known ID, or classified failure |

Every call carries a caller-generated UUID and a finite budget. Operation requests are versioned, validated and copied/frozen before first send; nested dictionaries must not change after binding. Field values use a bounded JSON value type with finite numbers. Request-specific validation rejects invalid identifiers, malformed selectors and unsupported payload types before I/O. Fields are already mapped by the caller; the gateway neither builds job payloads nor invents creation defaults. SOQL comes from trusted application callers, is encoded as data, and is never constructed by interpolating raw job text here.

Each method returns `GatewayResult[T]`: exactly one typed value or `GatewayFailure`, plus a safe attempt summary. `GatewayFailure` wraps `ClassifiedError` and typed fields for safe provider code, nullable HTTP status, operation kind, `remote_outcome` (`not_sent`, `rejected`, `unknown`, or `acknowledged`), `recovery_action` (`none`, `retry_later`, `reauthorize`, `reconcile`, or `fix_configuration`), optional UTC retry-not-before, and exhausted-budget status. An unknown write outcome is never reported as a confirmed rejection or success. Raw HTTP responses/exceptions stay below the public boundary.

Use `recoverable` to describe eligibility for automatic retry of this operation, not merely membership in `RECOVERABLE_CATEGORIES`. Construct it explicitly when replay is unsafe. A retry-later or reconcile hint does not schedule work: the caller owns persistence and later action. Record network attempt counts separately from C12 delivery attempts.

### Error and recovery contract

Classification uses operation context, HTTP status and an allowlisted Salesforce/OAuth code. It never relies on unbounded free-text matching or returns raw provider messages. Salesforce documents that a 403 can mean `REQUEST_LIMIT_EXCEEDED`, so it cannot always be classified as permission denial. [REST status/error reference](https://developer.salesforce.com/docs/platform/api-rest/guide/errorcodes.html)

| Observed failure | Category / result | Recovery |
|---|---|---|
| Missing org, grant, API version or credential reference | `missing_configuration`; not sent | No call; fix owning configuration/prerequisite |
| Explicit invalid/expired API session | `authentication` | At most one renewal through the SF-02 flow and one replay after a definite authentication rejection, within the same call budget; repeated rejection ends in reauthorization |
| Invalid grant/client, revoked credential, denied login | `authentication` | Stop; reauthorization/credential repair through established SF-02 procedure; no fallback flow |
| Explicit insufficient object/field/API access | `permission` | No renewal loop, no retry, no permission changes |
| `REQUEST_LIMIT_EXCEEDED` / known exhausted org API quota | `rate_limit`, distinct quota code | Return retry-later; no immediate quota polling or fabricated reset time |
| HTTP 429 with safe rate-limit evidence | `rate_limit` | Retry only when operation replay is permitted and Retry-After fits remaining budget; otherwise return retry-later |
| Storage exhaustion | `capacity` | No immediate automatic retry; return capacity remediation hint; no deletion/retention work |
| DNS/connect failure, disconnect, timeout | `transient_network` | Bounded retry only if replay is safe; after possible write transmission, report unknown and reconcile unless explicitly replay-safe |
| Retryable 5xx | `transient_service` | Same operation-specific bounds; a write may have committed despite failure |
| Invalid field/value, malformed query, required field, duplicate External ID match, unsupported method/resource | `validation` or `unsupported_input`, with permanent safe code | No retry; repair request/configuration. Never pick an arbitrary matching record |
| 404 / conflict / failed precondition | Permanent request failure with specific safe code | Preserve not-found/conflict semantics; no blind replay or inference that missing means deleted or permitted to recreate |
| TLS certificate/hostname failure, rejected redirect/origin/version | `permission` for transport policy or `missing_configuration` for configuration, distinct safe code | Fail closed; no TLS bypass or changed destination |
| Malformed/truncated success envelope | `transient_service`, protocol-error code | No automatic replay by default; potentially committed write is unknown/reconcile |
| Unknown 4xx or unmapped provider code | `unsupported_input`, permanent fallback code | Stop safely; preserve only bounded allowlisted diagnostics |

Do not add a new shared error enum merely to spell “permanent request failure.” Existing nonrecoverable categories plus stable codes are sufficient. Auth and quota classification must precede generic status fallback. Error arrays and OAuth error objects have separate bounded parsers.

### Bounded execution policy

Proposed initial ceilings: 10-second connect timeout, 20-second read-idle timeout, 60-second total logical-call deadline, at most **6 HTTP sends total**, at most **3 resource sends**, and at most **2 token-endpoint sends** (initial acquisition plus one renewal). All counters apply together, including authentication, retries and any explicit helper reads. No nested retry loop resets them. Queue/credential-lock wait, response reads and sleep consume the monotonic deadline. Caller-supplied budgets may lower these ceilings.

Use injected clock, sleeper and jitter; proposed exponential delays start at 1 second and cap at 8 seconds. Validate all limits as finite positive values. Parse Retry-After seconds and HTTP dates; never shorten a server-specified wait to retry early. If it exceeds remaining time, return a retry-not-before hint without sleeping past the deadline. Invalid/negative values use bounded fallback. Known org quota exhaustion returns immediately regardless of the short-backoff settings.

Reads can retry transient failures. Writes default to **no replay after uncertain transmission**. An External ID upsert may opt into replay only when the caller guarantees the same unique key and frozen payload, serialized ownership for that entity/version, and acceptable repeated side effects. A unique row alone does not make automation/Flows exactly-once. Known-ID updates remain conservative by default. No create/upload operation inherits upsert semantics. Token exchange replay follows its grant-specific rules; it does not inherit read or record-upsert retry policy.

## Ordered stories

All stories belong to **SFCLIENT-01**. Paths below `src/job_automation/` are relative to that package unless shown otherwise. Shared-file edits are narrow coordinated changes, not ownership transfers.

| Order | Story | Dependencies | Deliverable |
|---|---|---|---|
| 1 | SFCLIENT-01-S01 | FND-01; SF-02 prerequisite inventory | Typed gateway/failure/port contracts and legacy compatibility plan |
| 2 | SFCLIENT-01-S02 | S01 | Non-secret configuration, API-version enforcement and bounded HTTPS transport |
| 3 | SFCLIENT-01-S03 | S01–S02; actual SF-02 for production grant adapter | Protected credential lifecycle and authenticated sessions |
| 4 | SFCLIENT-01-S04 | S01–S03; fake auth may unblock tests | Typed reads and explicit record mutations |
| 5 | SFCLIENT-01-S05 | S02–S04 | Complete failure classification and operation-specific recovery |
| 6 | SFCLIENT-01-S06 | S01–S05 | Redaction, safe diagnostics and consumer integration checks |
| 7 | SFCLIENT-01-S07 | S01–S06; SF-02/SF-01 for live records | Native Windows checks, scoped live evidence and handoff |

### SFCLIENT-01-S01 — Freeze gateway contracts and dependency boundaries

**Objective / requirements.** Establish transport-only typed operations and replay/failure semantics without absorbing C12 ownership. R08/R15/R16.

**Inputs → outputs.** FND-01 protocol, C12 and error contracts; available prerequisite records → V2 protocol, versioned operation/result records, injected ports and documented migration plan. Unknown SF-02 fields remain an explicit prerequisite list.

**Owned files.** Proposed `contracts/salesforce.py`, `salesforce/{__init__,ports}.py`; narrow edits to `contracts/{interfaces,export_schemas}.py`; new gateway schemas under `schemas/v1/`; `tests/salesforce/test_contract_boundary.py`, `tests/fixtures/salesforce/`, `tests/fakes/salesforce_transport.py`. Extend foundation interface tests only for V2 conformance.

**Tasks.**

1. Freeze the public table above, result exclusivity, typed recovery/outcome metadata, immutable request binding and version 1.0 for new records. Add V2 as a new protocol without changing C12 or the legacy signature.
2. Define `HttpTransport`, `CredentialStore`, `TokenProvider`, clock/sleeper/jitter and safe recorder ports. Transport must report whether transmission is definitely absent or uncertain; uncertainty defaults conservatively. Tokens are runtime-only opaque secrets, not serializable contract fields.
3. Record consumer migration: existing fakes/renderer still use legacy; new gateway and fake consumer use V2; SYNC-01 later provides domain mapping/facade. Do not claim unfinished SYNC integration is done.
4. Specify limits on request/response bytes, JSON depth, field/record counts and continuation lifetime/binding. Export new schemas and synthetic positive/negative fixtures.

**Acceptance criteria.** A caller can describe an External ID upsert without importing C12 or passing an assessment. Both/neither result value and error are rejected. An ambiguous mutation is representable without a guessed record ID. Existing C12 fixtures and legacy protocol tests remain valid.

**Fake-transport tests.** Protocol conformance, fake consumer invocation, version rejection, JSON bounds, malformed selectors, caller dictionary mutation, and zero transport calls on invalid requests. No fake resides in the production package.

**Migration/configuration/handoff.** No storage migration. Record schema/protocol versions, compatibility table, approved file ownership and the still-missing SF-02 inputs. Reconcile any incompatible shared change before later stories proceed.

### SFCLIENT-01-S02 — Configure the API and enforce bounded HTTPS

**Objective / requirements.** Make destination, version and resource use explicit while preserving offline/unrelated commands. R08/R14/R15/R16.

**Inputs → outputs.** Optional non-secret Salesforce settings and validated operation route → configured transport or safe configuration failure. Imports, construction and `config check` make no network calls or credential reads.

**Owned files.** `salesforce/{configuration,transport}.py`; narrow `configuration.py` integration; `config/salesforce.example.json`, `schemas/v1/` config schemas and exporter; `tests/salesforce/{test_configuration,test_transport,test_deadlines}.py`; existing config tests. `pyproject.toml` only if a justified Windows-compatible dependency is necessary.

**Tasks.**

1. Add optional `salesforce_settings_ref` to AppConfig, resolved with `pathlib.Path` against the config parent. Missing settings affect only Salesforce execution. Keep secrets out of configuration; use opaque credential references. Existing example configs still load.
2. Require an explicit API version in `NN.0` format; embed it in every `/services/data/vNN.0/` route. Never silently use “latest,” downgrade or use an SDK's implicit version. OAuth endpoints remain separately configured and unversioned. Live capability confirmation occurs in S07.
3. Accept only SF-02-approved HTTPS authorization and API origins, with normal TLS hostname/certificate validation. Reject userinfo, fragments, unexpected ports/paths and caller-supplied destination overrides. Validate token-returned instance origins before use; a changed host requires approved configuration, not automatic trust.
4. Disable automatic redirects and implicit environment proxy routing. Any required enterprise proxy/trust configuration must be explicit and verified without disabling TLS. Percent-encode selector values and query parameters; validate API identifiers independently.
5. Enforce total and idle timeouts, request/response bounds and reliable resource closure, including slow trickle responses. Verify continuation paths stay on the bound org/version and query route; reject absolute foreign URLs, traversal and scheme-relative paths.

**Acceptance criteria.** Missing/invalid API version fails before HTTP. A token response, redirect or query continuation cannot redirect bearer credentials to another origin. A stalled response terminates within budget. Unrelated commands still work with no Salesforce settings.

**Fake-transport tests.** Versioned route assertions; object/External ID encoding with spaces, Unicode and reserved characters; forbidden origins, redirect/proxy traps, TLS failures, oversized/chunked/trickling responses and closure. Exercise the real transport policy through injected connections as well as gateway-level fakes.

**Migration/configuration/handoff.** Document settings/units/ceilings and dependency versions. Old readers with `extra='forbid'` cannot read new config keys: retain old examples and document the minimum reader version. No schema deployment or database migration.

### SFCLIENT-01-S03 — Consume SF-02 authentication and protect token lifecycle

**Objective / requirements.** Authenticate using the already selected flow and Windows credential mechanism, with safe renewal/revocation handling. R15/R16/R14.

**Inputs → outputs.** Completed SF-02 configuration record, opaque credential reference and token-provider request → validated in-memory session or classified failure. The grant-specific production path is blocked until that record exists; synthetic token-provider tests are not proof of a chosen flow.

**Owned files.** `salesforce/{auth,credentials}.py`, composition in `salesforce/gateway.py`; `tests/salesforce/{test_auth,test_credentials,test_token_rotation}.py`; fake credential store and synthetic auth responses under `tests/fakes/` and `tests/fixtures/salesforce/`.

**Tasks.**

1. Implement only SF-02's selected grant, including its exact client authentication/audience/PKCE or assertion requirements where applicable. No password fallback, alternate grant, new app registration or inbound worker endpoint. If initial interactive consent is required, consume the established bootstrap procedure; normal operations do not launch repeated consent flows.
2. Use SF-02's protected Windows store/key references. Do not store access tokens in SQLite, JSON config, logs or source files. Persist renewable credentials only using the established protected mechanism. If secure storage is unavailable, fail rather than fall back to plaintext.
3. Cache access tokens in memory; honor reliable expiry metadata with bounded clock skew, and handle server-side invalidation when expiry is unknown. Do not assume every token response contains `expires_in` or a refresh token. Validate required response fields and the bound origin before any resource call.
4. Renew only as allowed by the selected grant. On explicit invalid-session rejection, invalidate the cached session and permit one renewal/replay. Serialize renewal for a shared credential; use protected-store versioning/locking across competing processes, or reject concurrent credential use. Bound lock wait. RUN-01 still owns the wider worker lock.
5. Where refresh rotation applies, save the replacement atomically before permitting further use; retain the prior credential only when the response validly omits a replacement under the established policy. Persist a protected exchange-in-progress marker before sending a single-use credential, then clear it atomically with successful credential replacement. If a rotating exchange may have succeeded but its response/store commit was lost, do not blindly reuse the old token. Return reauthorization/recovery-required and prevent unsafe restart reuse. This credential-store state is not a C12 outbox.
6. Treat revoked/expired refresh credentials, invalid assertions and changed key references as explicit repair conditions. Clearing a local cache does not revoke the org credential. Remote revocation or rotation of authorization assets stays in SF-02's operational procedure.

**Acceptance criteria.** An absent credential yields no resource request. A valid cached token avoids redundant acquisition. A rejected access token causes at most one renewal; invalid grant stops immediately. A replacement refresh token survives restart securely; an uncertain rotating exchange cannot cause an endless refresh loop.

**Fake-transport tests.** Acquisition, cache reuse, known/unknown expiry, repeated 401, renewal success/denial, missing/malformed token fields, wrong instance origin, concurrent renewal, lock timeout, secure-store failure, rotation replacement and restart, lost token-response and interrupted persistence. Exercise only the actual grant adapter once supplied; generic port tests remain labeled synthetic.

**Migration/configuration/handoff.** Record exact SF-02 evidence and selected adapter/store, non-secret recovery instructions and native Windows store verification. No authorization assets created or modified. Salesforce's rotation documentation warns that replaying an already rotated refresh token can invalidate the current session, which motivates the conservative uncertainty rule. [Refresh token flow](https://help.salesforce.com/s/articleView?id=sf.remoteaccess_oauth_refresh_token_flow.htm&language=en_US&type=5)

### SFCLIENT-01-S04 — Implement typed reads and caller-mapped record operations

**Objective / requirements.** Execute the supported operation set with strict wire-response validation and explicit acknowledgment semantics. R08/R15/R16.

**Inputs → outputs.** V2 requests, approved session and API version → typed records/pages/capabilities/acknowledgments or failures. Caller-mapped field values pass unchanged except for documented wire serialization.

**Owned files.** `salesforce/{gateway,operations,serialization}.py`; `tests/salesforce/{test_reads,test_pagination,test_upserts,test_updates,test_response_validation}.py`; synthetic wire fixtures.

**Tasks.**

1. Implement explicit connection verification, limits, describe, selected record reads and one-page query execution. Bind connection verification to SF-02's available identity evidence and the supported-version discovery endpoint; missing access is a prerequisite failure, not a request for broader scopes. Validate envelopes/IDs/counts/continuation consistency. Empty records are successful only when the response establishes an empty page; a failed later page is not completion of the query. No implicit full-org traversal.
2. Implement External ID PATCH upsert and known-ID PATCH update with immutable payloads and stable selectors. Reject missing/empty External ID and special null-ID create patterns. Never append user-owned defaults, derive field names from C12, select jobs or perform automatic field filtering that could hide mapping mistakes.
3. Freeze endpoint/version-specific success rules. Current Salesforce documentation distinguishes upsert insertion (201) from update (200 for API 46.0+; historical versions used 204). Known-ID PATCH has its own no-content acknowledgment semantics. Do not assume every PATCH returns a body or every 204 is an upsert success. [External ID upsert reference](https://developer.salesforce.com/docs/platform/api-rest/guide/dome-upsert.html)
4. Require returned ID/created evidence where promised by the configured upsert version. A missing/invalid acknowledgment after mutation is an unknown outcome, not a guessed success. If historical no-ID upsert responses are supported, define an explicit bounded ID lookup and preserve acknowledgment separately from lookup failure; otherwise reject that unsupported API version before execution.
5. Treat duplicate External ID matches as a permanent ambiguity. Return explicit not-found/permission results; do not create replacements on failed reads. Leave all local/remote ID persistence and version ordering to SYNC-01.

**Acceptance criteria.** A fake insertion and update yield the same logical key with valid acknowledgments. The exact caller field set is sent; no status/notes/default fields are added. Failed reads do not become empty successful datasets. Unsupported operations have no HTTP escape route.

**Fake-transport tests.** Exact methods/routes/headers/body; create/update upsert variants for the supported version; 204 known-ID update; invalid/missing IDs; duplicate matches; missing fields; two query pages with second-page failure; hostile cursor; Unicode serialization; null field versus omitted field; payload mutation after first send. Callers can read permitted candidate-owned fields without the client deciding backup/publication policy.

**Migration/configuration/handoff.** Publish supported endpoint/version behavior and typed examples for SYNC-01. No C12 or storage migrations; no polling worker, Files upload or publication pipeline.

### SFCLIENT-01-S05 — Classify failures and apply bounded recovery

**Objective / requirements.** Distinguish repair, deferred retry and reconciliation, and bound every automatic recovery path. R15/R16.

**Inputs → outputs.** Transport failures, bounded response envelopes, request replay policy and remaining budget → classified terminal result or permitted retry with complete safe attempt metadata.

**Owned files.** `salesforce/{errors,retry,budget}.py`; integration in auth/gateway/transport; `tests/salesforce/{test_error_classification,test_recovery,test_retry_after,test_ambiguous_writes,test_budgets}.py`.

**Tasks.**

1. Implement the classification table and separate error parsers. Provider codes take precedence where they distinguish quota, permission and authentication. Use fixed safe messages and bounded allowlisted codes; unknown errors cannot leak response text.
2. Apply one shared logical-call budget across resource calls, auth acquisition/renewal, sleeps and helper reads. Retries use the frozen request, identity and version. HTTP libraries must not add hidden retries.
3. Implement read retry, conservative mutation behavior and explicit replay-safe upsert opt-in. Definite rejection is different from a lost response. Do not retry token rotation after uncertain transmission or retry capacity/quota exhaustion in a tight loop.
4. Return actionable terminal recovery metadata on every exhaustion path. Caller-owned outbox attempts/deadlines must be able to further restrict the gateway; C12 `max_attempts` never silently becomes a second independent transport loop.

**Acceptance criteria.** A 403 quota failure differs from a 403 permission failure. A 401 followed by successful renewal and 503 remains under the original caps/deadline. A lost write response returns unknown/reconcile by default; a permitted identical-key upsert replay remains within bounds. No uncertain file/create replay capability is introduced.

**Fake-transport tests.** Table-driven coverage for every classification row; malformed/non-JSON OAuth and REST errors; 429 seconds/date/past/invalid/too-long Retry-After; exhausted quota; connect-before-send versus read-after-send failures; 5xx after commit; repeated auth failure; renewal plus backoff plus lookup aggregate budgets; exact-cap/one-over; fake slow clock and lock wait; unsafe update sent once; opted-in upsert repeats identical bytes/key. A stateful fake asserts one logical row while separately counting repeated side effects; it does not prove exactly-once automation.

**Migration/configuration/handoff.** Document category/code/recovery mapping, limits and replay guarantees. No durable retry scheduling, per-job ordering, stale-write detection or reconciliation workflow is implemented here.

### SFCLIENT-01-S06 — Verify secret-safe diagnostics and consumer wiring

**Objective / requirements.** Make failures diagnosable without exposing credentials or payload data. R15/R16.

**Inputs → outputs.** Operation context and execution events → allowlisted diagnostic records and safe public errors; a fake consumer can use the complete production gateway through injected dependencies.

**Owned files.** `salesforce/diagnostics.py`, package exports/composition; `tests/salesforce/{test_safe_diagnostics,test_consumer_boundary,test_gateway_integration}.py`; narrow config-error rendering changes/tests in `cli.py` only if needed.

**Tasks.**

1. Emit only call ID, operation kind, configured API version, attempt purpose/count, status, safe provider code, UTC event time, monotonic duration, recovery/outcome and safe numeric quota observations. Omit bearer headers, credentials, token bodies, key material, cookies, SOQL, record bodies, selector values and raw URLs.
2. Keep secrets out of `repr`, Pydantic validation errors, chained exceptions, stderr and HTTP debug logging. Do not pass raw request/response exceptions to normal loggers; a secret wrapper alone is insufficient.
3. Test production composition against scripted transport/store/clock and an injected safe recorder. Recorder failures must not replay a successful mutation or leak the original event. Do not import storage repositories, assessment/publication logic or source adapters into the gateway.

**Acceptance criteria.** Distinct auth/permission/quota/network/permanent failures remain diagnosable using codes and call IDs. Sentinel secrets and candidate text never appear in logs, exceptions, configuration failures, serialized diagnostics or test reports produced by the public path. Success/failure contracts hold through the same composition intended for production.

**Fake-transport tests.** Inject sentinels into headers, token endpoints, OAuth error descriptions, response bodies, nested SDK/transport exceptions and invalid configuration. Capture logging/stdout/stderr/repr/serialization. Verify recorder failure after acknowledged write causes no repeat request; verify no database/outbox side effects.

**Migration/configuration/handoff.** Publish the diagnostic allowlist and safe troubleshooting instructions. Durable run logging/retention remains with its existing owners; secrets never enter schema fixtures or handoff output.

### SFCLIENT-01-S07 — Verify native Windows and the existing org, then hand off

**Objective / requirements.** Demonstrate offline behavior and separately record narrow live acceptance using the established authorization. R08/R14/R15/R16.

**Inputs → outputs.** Completed implementation/tests plus actual SF-02 access and an explicitly scoped record fixture → reproducible check results and `docs/components/SFCLIENT-01.md`. Missing prerequisites yield pending live evidence, not a replacement authorization project.

**Owned files.** `tests/manual/salesforce_smoke.py`, `tests/salesforce/{test_windows_paths,test_smoke_guards}.py`, `docs/components/SFCLIENT-01.md`; concise README verification instructions if needed. No org metadata files.

**Tasks and scoped verification.**

1. Run contract/fake-transport and affected config/interface tests. The normal suite must not resolve real credentials or access Salesforce. Make live smoke a separate, opt-in script with read-only default and safe output.
2. On native Windows, test config/key-reference paths with spaces and non-ASCII characters, a different working directory, inaccessible/missing protected credentials and restart behavior. Use the SF-02 execution identity. Fake store success alone does not verify Windows protection. No scheduled startup/logged-out acceptance belongs here.
3. Live read-only gate: resolve the existing credential, verify the expected org identity using an approved endpoint, confirm the configured API version is supported, perform one small permitted query/record read and describe only the integration's known target object. Fetch limits only if granted. An unavailable limits endpoint is a permission/capability result, not a reason to expand access. Never dump records or full org inventory into the handoff.
4. Live mutation gate: require an explicitly authorized synthetic test key, existing target object/External ID and exact field/value set, plus confirmed unique-ID/access prerequisites. Developer Edition is not automatically a disposable sandbox. Inspect that key first; stop if it belongs to unrelated data. Use one isolated record, upsert a synthetic value, repeat the same key, update only the agreed field, and read back the permitted fields/record ID to verify one logical row. Check selected pre-existing user-owned field values remain unchanged without logging their contents. Existing Flows/default behavior is SF-01/02 evidence, not something to repair here.
5. Record allowed maximum calls/runtime before starting and stop on quota/permission errors. Never exhaust quotas, revoke real credentials, induce outages or probe unrelated objects for testing. Inject expired sessions, denied permissions, rate limits and ambiguous writes in fake tests; exercise live renewal only through the established non-destructive lifecycle when feasible.
6. Agree fixture disposition with the mutation authorization. Leave the synthetic record documented by a safe reference unless cleanup was explicitly included. Generic delete support is not needed; any authorized cleanup uses existing owner tooling scoped to that record and is recorded. Stop and report collisions, unexpected automation or unmet prerequisites.

**Acceptance criteria.** Offline checks pass without service access. Live read and record results are each marked passed/pending/failed with precise reasons. Correct API version and established identity are evidenced; no secrets or real record content enter artifacts. Missing SF-02 keeps the production/live portion pending. Declare VERIFIED only when declared component acceptance is demonstrated; otherwise distinguish implemented offline behavior from pending integration.

**Fake-transport tests.** Smoke defaults perform only read operations; absent mutation flag/fixture/expected-org evidence causes no write; wrong-org/collision/budget guards stop before mutation; same-key fixture is reused; cleanup cannot target arbitrary records. Repeat safe-output checks on the smoke path.

**Migration/configuration/handoff.** No metadata or database migration. Record every prerequisite, final public contract, actual selected grant/store without secrets, tested API/dependency versions, file ownership, commands/results, outstanding live/Windows checks and next consumer **SYNC-01**. GEN-01/GEN-06 remain future consumers, not deliverables of this component.

## Verification commands and completion checklist

The following are **planned implementation checks**, not commands run or tests passed during this story-planning task. Run from the repository root using native PowerShell once the proposed files exist:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\salesforce tests\contracts\test_interfaces.py tests\contracts\test_work_records.py tests\test_configuration.py tests\test_cli.py
& ".\.venv\Scripts\python.exe" -m job_automation config check --config ".\config\app.example.json" --data-root (Join-Path $env:LOCALAPPDATA "Job Automation Prüfung ä")

# Only after SF-02 prerequisites are supplied; proposed smoke interface, read-only default.
& ".\.venv\Scripts\python.exe" ".\tests\manual\salesforce_smoke.py" --config (Join-Path $env:LOCALAPPDATA "Job Automation Prüfung ä\app.json")
```

The eventual smoke mutation invocation must name the authorized fixture and explicit write option; document exact syntax after implementation. Never pass tokens, client secrets, assertions or private keys on the command line. Schema regeneration checks must target the newly added Salesforce/config contracts and verify deterministic output without unrelated schema churn.

- [ ] All seven stories retain SFCLIENT-01 ownership; no publication/mapping/outbox/auth-asset implementation slipped in.
- [ ] FND-01 legacy contracts remain compatible; new gateway contracts, schemas and fake consumers agree.
- [ ] SF-02 configuration evidence is present or explicitly absent; the actual grant is never inferred from examples.
- [ ] Unit/contract, fake integration, native Windows and live Salesforce evidence are reported separately.
- [ ] Typed success, definite rejection and unknown outcome remain distinct; replay is operation-specific and bounded.
- [ ] Configured API version, TLS/origin controls and secret-safe logs are verified.
- [ ] SYNC-01 receives operations, acknowledgments, recovery hints and compatibility guidance without surrendering its mapping/outbox ownership.

Planning result: no application code implemented, no credentials inspected, no org access or mutation performed, and no live acceptance claimed. The absent SF-02 handoff/configuration remains a named prerequisite.
