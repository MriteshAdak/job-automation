"""Arbeitnow Job Board API adapter (SOURCE-03-arbeitnow).

Fetches from https://www.arbeitnow.com/api/job-board-api (free, no auth required).
Maps provider fields into C05 RawPosting / SourceJobDraft without normalisation.

Official evidence reviewed 2026-10-28 UTC:
  E1  https://www.arbeitnow.com/blog/job-board-api        (API announcement)
  E2  https://documenter.getpostman.com/view/18545278/UVJbJdKh  (Postman docs)
  E3  https://www.arbeitnow.com/terms                     (Terms of service)

Access: §11 permits free API use on an as-available basis; access may be revoked.
        E3 §2 limits website-material copying/public display separately.
        Persistent storage and Salesforce transfer scope remain under review (U07).

Attribution: §11 requires a link back to Arbeitnow.com on the platform.
             API meta.info also requests link-back per retrieved documentation.
             Adapter propagates: notice="Source: Arbeitnow", link="https://www.arbeitnow.com"

Uncertainties deferred to downstream components (see docs/stories/SOURCE-03-arbeitnow.md):
  U01 Current feed may differ from 2021 saved schema.
  U02 Terminal-page and empty-page live behaviour unverified.
  U03 Current rate quota and window unknown.
  U04 Slug permanence and recycling undocumented.
  U05 created_at unit and event meaning unresolved — source_published_raw=None.
  U06 Completeness and retention horizon unverified.
  U07 Retention/transfer permission scope under review.
  U08 Durable sink integration is INGEST-01/DATA-01 work.
  U09 No shared C05 attribution field; provider-local metadata extension used.
"""

from __future__ import annotations

import copy
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    DraftResult,
    RecordIssue,
)
from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.adapters.binding import (
    validate_adapter_binding,
    verify_runtime_config,
)
from job_automation.sources.adapters.mapping import map_raw_record_to_draft_fields
from job_automation.sources.adapters.raw import RawCaptureSink, compute_content_hash
from job_automation.sources.models import AttributionStatus, EffectiveSource

# ── Adapter constants ──────────────────────────────────────────────────────────

ADAPTER_NAME = "arbeitnow-v1"
PROVIDER = "arbeitnow"
BOARD_ID = "default"          # Local namespace for the .com feed; not a provider-issued ID
ENVELOPE_VERSION = "arbeitnow-env-v1"
MAPPING_ID = "arbeitnow-map-v1"
ATTRIBUTION_NOTICE = "Source: Arbeitnow"
ATTRIBUTION_LINK = "https://www.arbeitnow.com"

# Strict URL allowlist per S01 decisions
ALLOWED_HOSTS: frozenset[str] = frozenset({"arbeitnow.com", "www.arbeitnow.com"})
ALLOWED_PATH = "/api/job-board-api"
ALLOWED_QUERY_KEYS: frozenset[str] = frozenset({"page"})

MAX_BODY_BYTES = 10 * 1024 * 1024   # 10 MiB conservative test budget, not a provider limit
MAX_REDIRECT_HOPS = 2
CONTINUATION_KIND = "page"
DEFAULT_PAGE = 1


# ── Injected protocol interfaces ───────────────────────────────────────────────


@runtime_checkable
class HttpTransport(Protocol):
    """Injected HTTP transport — one GET attempt, no retry.

    Returns (status_code, headers_as_lowercase_dict, body_bytes).
    Raises TimeoutError on timeout, OSError on connection failure.
    """

    def get(self, url: str, timeout: float) -> tuple[int, dict[str, str], bytes]: ...


@runtime_checkable
class ClockProtocol(Protocol):
    """Injected clock for deterministic UTC timestamps in tests."""

    def now_utc(self) -> datetime: ...


# ── Default production implementations ────────────────────────────────────────


class _UrllibTransport:
    """Default stdlib urllib transport — one attempt, redirect handling disabled.

    Redirect targets are validated by the adapter before being followed;
    this transport returns 3xx responses rather than auto-following them.
    """

    def get(self, url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "job-automation/0.1 (arbeitnow-v1; SOURCE-03)")
        req.add_header("Accept", "application/json")

        # Build opener that does NOT auto-follow redirects
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
                return None

        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(req, timeout=timeout) as resp:
                status: int = resp.status
                headers = {k.lower(): v for k, v in resp.headers.items()}
                body = resp.read(MAX_BODY_BYTES + 1)
                return status, headers, body
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read(MAX_BODY_BYTES + 1)
            except Exception:
                pass
            hdrs = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
            return exc.code, hdrs, body


class _SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(tz=timezone.utc)


# ── URL validation helpers ─────────────────────────────────────────────────────


def validate_arbeitnow_url(url: str) -> tuple[bool, int | None]:
    """Validate a URL against the Arbeitnow adapter allowlist.

    Returns (is_valid, page_number_or_None).
    page_number is None when no ``?page=`` parameter is present.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, None

    if parsed.scheme != "https":
        return False, None

    # Reject userinfo (credentials in URL)
    if parsed.username or parsed.password:
        return False, None

    # Reject fragments
    if parsed.fragment:
        return False, None

    # Host check (netloc may include port; hostname is just the name part)
    host = parsed.hostname or ""
    if host not in ALLOWED_HOSTS:
        return False, None

    # Explicit port must be 443 or absent
    if parsed.port is not None and parsed.port != 443:
        return False, None

    # Path must match exactly
    if parsed.path != ALLOWED_PATH:
        return False, None

    # Query keys must be from the allowlist
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    unknown_keys = set(params.keys()) - ALLOWED_QUERY_KEYS
    if unknown_keys:
        return False, None

    # Duplicate page params are not allowed
    page_num: int | None = None
    if "page" in params:
        page_vals = params["page"]
        if len(page_vals) != 1:
            return False, None
        try:
            page_num = int(page_vals[0])
            if page_num < 1:
                return False, None
        except (ValueError, TypeError):
            return False, None

    return True, page_num


def build_page_url(page_num: int) -> str:
    """Return the canonical Arbeitnow API URL for a given page number."""
    return f"https://www.arbeitnow.com{ALLOWED_PATH}?page={page_num}"


def _safe_url_summary(url: str) -> str:
    """Return a safe scheme+host summary for diagnostic messages (no credentials)."""
    try:
        p = urllib.parse.urlparse(url)
        return f"{p.scheme}://{p.hostname}[...]"
    except Exception:
        return "[url]"


def _url_identity_fallback(url: str) -> str:
    """Derive the ``url-v1:sha256:<hex64>`` fallback posting ID from a validated URL."""
    url_bytes = url.strip().encode("utf-8")
    hex_hash = hashlib.sha256(url_bytes).hexdigest()
    return f"url-v1:sha256:{hex_hash}"


# ── Main adapter class ─────────────────────────────────────────────────────────


class ArbeitnowAdapter:
    """Arbeitnow Job Board API adapter.

    Implements the ``Adapter`` Protocol boundary (interfaces.py):
      fetch_page(config, continuation) -> AdapterPage
      draft_posting(raw) -> DraftResult

    Each ``fetch_page`` call fetches exactly one page.  Pagination continuation
    tokens are passed between calls by the consumer (INGEST-01).

    Construction and import perform no network I/O or directory creation.
    The adapter is bound to one ``EffectiveSource`` for its lifetime.
    """

    def __init__(
        self,
        effective_source: EffectiveSource,
        capture_sink: RawCaptureSink,
        transport: HttpTransport | None = None,
        clock: ClockProtocol | None = None,
    ) -> None:
        self._source = effective_source
        self._sink = capture_sink
        self._transport: HttpTransport = transport if transport is not None else _UrllibTransport()
        self._clock: ClockProtocol = clock if clock is not None else _SystemClock()
        # Validate binding immediately at construction (before any I/O)
        self._validate_binding()

    # ── Binding validation ─────────────────────────────────────────────────────

    def _validate_binding(self) -> None:
        """Enforce adapter-specific binding checks beyond the shared helper."""
        # Shared helper: enabled, permitted access, correct acquisition method
        validate_adapter_binding(
            source=self._source,
            supported_method=AcquisitionMethod.API,
            adapter_name=ADAPTER_NAME,
        )
        cfg = self._source.config

        if cfg.provider != PROVIDER:
            raise ValueError(
                f"ArbeitnowAdapter requires provider '{PROVIDER}', got '{cfg.provider}'"
            )
        if cfg.board_id != BOARD_ID:
            raise ValueError(
                f"ArbeitnowAdapter requires board_id '{BOARD_ID}', got '{cfg.board_id}'"
            )
        if cfg.inventory_semantics == InventorySemantics.COMPLETE_BOARD:
            raise ValueError(
                "ArbeitnowAdapter does not support 'complete_board' semantics. "
                "The Arbeitnow feed cannot guarantee complete board coverage; use 'filtered_feed'."
            )
        attr = self._source.attribution_review
        if attr.status not in (AttributionStatus.REQUIRED, AttributionStatus.NONE_REQUIRED):
            raise ValueError(
                f"ArbeitnowAdapter requires attribution_review.status 'required' or 'none_required', "
                f"got '{attr.status.value}'. Review attribution before enabling."
            )

    # ── HTTP layer ─────────────────────────────────────────────────────────────

    def _make_request(
        self, url: str, timeout: float
    ) -> tuple[int, dict[str, str], bytes] | ClassifiedError:
        """Execute one GET with allowlist-validated redirect handling.

        Returns (status, headers, body) or a ClassifiedError.
        Response bytes are returned raw; caller handles capture and size checks.
        """
        current_url = url
        hops_used = 0

        while True:
            try:
                status, headers, body = self._transport.get(current_url, timeout)
            except TimeoutError:
                return ClassifiedError.from_category(
                    ErrorCategory.TRANSIENT_NETWORK,
                    message="Request timed out",
                    details={"url_safe": _safe_url_summary(current_url)},
                )
            except OSError as exc:
                return ClassifiedError.from_category(
                    ErrorCategory.TRANSIENT_NETWORK,
                    message=f"Connection error: {type(exc).__name__}",
                    details={"url_safe": _safe_url_summary(current_url)},
                )

            if status not in (301, 302, 303, 307, 308):
                return status, headers, body

            # Redirect — validate target before following
            hops_used += 1
            if hops_used > MAX_REDIRECT_HOPS:
                return ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    message=f"Too many redirects (limit {MAX_REDIRECT_HOPS})",
                    details={"code": "redirect_limit_exceeded"},
                )

            location = headers.get("location", "")
            if not location:
                return ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    message="Redirect response missing Location header",
                )

            # Resolve relative Location against current URL
            resolved = urllib.parse.urljoin(current_url, location)
            is_valid, _ = validate_arbeitnow_url(resolved)
            if not is_valid:
                return ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    message="Redirect target fails Arbeitnow URL allowlist; request stopped",
                    details={"code": "redirect_disallowed"},
                )
            current_url = resolved

    def _classify_http_error(
        self,
        status: int,
        headers: dict[str, str],
        _body: bytes,
    ) -> ClassifiedError:
        """Map an HTTP status to a classified error."""
        if status == 401:
            return ClassifiedError.from_category(
                ErrorCategory.AUTHENTICATION,
                message="Arbeitnow API returned 401 Unauthorized",
            )
        if status == 403:
            return ClassifiedError.from_category(
                ErrorCategory.PERMISSION,
                message="Arbeitnow API returned 403 Forbidden",
            )
        if status == 404:
            return ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                message="Arbeitnow API returned 404 Not Found; check endpoint configuration",
            )
        if status == 429:
            details: dict[str, Any] = {"code": "rate_limited"}
            ra = headers.get("retry-after")
            if ra:
                details["retry_after"] = ra
            return ClassifiedError.from_category(
                ErrorCategory.RATE_LIMIT,
                message="Arbeitnow API returned 429 Too Many Requests",
                details=details,
            )
        if status == 304:
            return ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                message=(
                    "Arbeitnow API returned 304 Not Modified without prior cache negotiation; "
                    "treating as an error, not an empty page"
                ),
            )
        if 500 <= status < 600:
            return ClassifiedError.from_category(
                ErrorCategory.TRANSIENT_SERVICE,
                message=f"Arbeitnow API returned server error {status}",
            )
        return ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            message=f"Arbeitnow API returned unexpected HTTP status {status}",
        )

    # ── Pagination helpers ─────────────────────────────────────────────────────

    def _extract_next_page(
        self, links: dict[str, Any], current_page: int
    ) -> tuple[int | None, ClassifiedError | None]:
        """Extract and validate the next page number from the response links dict.

        Returns one of:
          (page_number, None)       — valid forward continuation
          (None, None)              — terminal page (links.next is null)
          (None, ClassifiedError)   — pagination error
        """
        next_url = links.get("next")
        if next_url is None:
            return None, None  # Explicit null → terminal per S03 proposed rule

        if not isinstance(next_url, str) or not next_url.strip():
            return None, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                message="links.next is not a non-empty string",
                field_path="links.next",
            )

        is_valid, page_num = validate_arbeitnow_url(next_url.strip())
        if not is_valid:
            return None, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                message="links.next URL fails Arbeitnow allowlist (wrong host, path, or query)",
                field_path="links.next",
                details={"code": "next_url_disallowed"},
            )

        if page_num is None:
            # URL is valid but has no ?page= param — no forward progress determinable
            return None, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                message="links.next has no page query parameter; cannot determine next page",
                field_path="links.next",
            )

        if page_num <= current_page:
            return None, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                message=(
                    f"links.next page {page_num} does not advance beyond "
                    f"current page {current_page}"
                ),
                field_path="links.next",
                details={"code": "non_forward_pagination"},
            )

        return page_num, None

    # ── Record identity helpers ────────────────────────────────────────────────

    def _build_source_key(
        self,
        job: dict[str, Any],
        record_index: int,
        parent_ref: str,
        parent_hash: str,
    ) -> SourceKey | RecordIssue:
        """Derive SourceKey from slug (preferred) or URL fallback."""
        slug = job.get("slug")

        # Type check slug first
        if slug is not None and not isinstance(slug, str):
            return RecordIssue(
                input_ref=parent_ref,
                input_hash=parent_hash,
                record_index=record_index,
                field_path=f"data[{record_index - 1}].slug",
                code="invalid_slug_type",
                severity="error",
                message=f"slug must be a string, got {type(slug).__name__}",
                category=ErrorCategory.VALIDATION,
            )

        if slug is not None and slug.strip():
            # Exact slug — never split numeric suffix, preserve case/leading zeros
            return SourceKey(
                provider=PROVIDER, board_id=BOARD_ID, source_posting_id=slug
            )

        # URL fallback path
        url = job.get("url")
        if url is not None and not isinstance(url, str):
            return RecordIssue(
                input_ref=parent_ref,
                input_hash=parent_hash,
                record_index=record_index,
                field_path=f"data[{record_index - 1}].url",
                code="invalid_url_type_for_fallback",
                severity="error",
                message=f"slug absent/blank; url must be a string for fallback, got {type(url).__name__}",
                category=ErrorCategory.VALIDATION,
            )

        if url is not None and url.strip():
            return SourceKey(
                provider=PROVIDER,
                board_id=BOARD_ID,
                source_posting_id=_url_identity_fallback(url.strip()),
            )

        # Neither slug nor URL available
        return RecordIssue(
            input_ref=parent_ref,
            input_hash=parent_hash,
            record_index=record_index,
            field_path=f"data[{record_index - 1}].slug",
            code="missing_posting_identity",
            severity="error",
            message="Record has no usable slug or url to establish source identity",
            category=ErrorCategory.VALIDATION,
        )

    # ── Envelope serialisation ─────────────────────────────────────────────────

    def _serialize_envelope(
        self,
        job: dict[str, Any],
        parent_ref: str,
        parent_hash: str,
        record_index: int,
    ) -> bytes:
        """Serialise the provider-owned derived envelope to deterministic UTF-8 bytes.

        The envelope links back to original response bytes and carries attribution.
        It is not a byte-exact substring of the response body.
        """
        envelope: dict[str, Any] = {
            "envelope_version": ENVELOPE_VERSION,
            "record": job,
            "capture": {
                "parent_ref": parent_ref,
                "parent_hash": parent_hash,
                "record_index": record_index,
                "mapping_id": MAPPING_ID,
                "attribution": {
                    "notice": ATTRIBUTION_NOTICE,
                    "link": ATTRIBUTION_LINK,
                },
            },
        }
        # ensure_ascii=False to preserve non-ASCII text faithfully
        return json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # ── Adapter Protocol: fetch_page ───────────────────────────────────────────

    def fetch_page(
        self,
        config: SourceConfig,
        continuation: Continuation | None = None,
    ) -> AdapterPage:
        """Fetch one page from the Arbeitnow API and return a C05 AdapterPage.

        Capture happens before JSON parsing.  A parent capture failure stops the
        page without fabricating a reference.  Record issues are isolated so valid
        neighbours are preserved.
        """
        # Runtime config must match the bound source
        try:
            verify_runtime_config(self._source, config)
        except ValueError as exc:
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=False,
                page_error=ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    message=str(exc),
                ),
            )

        # Resolve page number from continuation or default
        current_page = DEFAULT_PAGE
        if continuation is not None:
            if continuation.kind != CONTINUATION_KIND:
                return AdapterPage(
                    items=[],
                    issues=[],
                    exhausted=False,
                    continuation_in=continuation,
                    page_error=ClassifiedError.from_category(
                        ErrorCategory.VALIDATION,
                        message=(
                            f"Unsupported continuation kind '{continuation.kind}'; "
                            f"expected '{CONTINUATION_KIND}'"
                        ),
                    ),
                )
            try:
                page_val = int(continuation.value)
                if page_val < 1:
                    raise ValueError("negative/zero")
            except (ValueError, TypeError):
                return AdapterPage(
                    items=[],
                    issues=[],
                    exhausted=False,
                    continuation_in=continuation,
                    page_error=ClassifiedError.from_category(
                        ErrorCategory.VALIDATION,
                        message=(
                            f"Continuation value '{continuation.value}' is not a "
                            f"valid positive integer page number"
                        ),
                    ),
                )
            current_page = page_val

        url = build_page_url(current_page)
        timeout = self._source.request_policy.timeout_seconds
        fetch_time = self._clock.now_utc()

        # Single HTTP attempt (no retry — INGEST-01 owns retry scheduling)
        result = self._make_request(url, timeout)
        if isinstance(result, ClassifiedError):
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=False,
                continuation_in=continuation,
                page_error=result,
            )

        status, headers, body = result

        # Capture raw response bytes BEFORE any parsing
        try:
            parent_ref, parent_hash = self._sink.capture(
                body, f"arbeitnow_page_{current_page}"
            )
        except Exception as exc:
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=False,
                continuation_in=continuation,
                page_error=ClassifiedError.from_category(
                    ErrorCategory.CAPACITY,
                    message="Failed to capture raw response bytes",
                    details={"error_type": type(exc).__name__},
                ),
            )

        # Body size guard (after capture so the reference is safe)
        if len(body) > MAX_BODY_BYTES:
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=False,
                continuation_in=continuation,
                raw_response_refs=[parent_ref],
                page_error=ClassifiedError.from_category(
                    ErrorCategory.CAPACITY,
                    message=(
                        f"Response body ({len(body)} bytes) exceeds "
                        f"{MAX_BODY_BYTES // (1024 * 1024)} MiB adapter limit"
                    ),
                ),
            )

        # Non-200 HTTP status
        if status != 200:
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=False,
                continuation_in=continuation,
                raw_response_refs=[parent_ref],
                page_error=self._classify_http_error(status, headers, body),
            )

        # Decode UTF-8 and parse JSON
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=False,
                continuation_in=continuation,
                raw_response_refs=[parent_ref],
                page_error=ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    message="Response body is not valid UTF-8",
                    details={"error_type": type(exc).__name__},
                ),
            )
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError as exc:
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=False,
                continuation_in=continuation,
                raw_response_refs=[parent_ref],
                page_error=ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    message="Response body is not valid JSON",
                    details={"error_type": type(exc).__name__},
                ),
            )

        # Validate root envelope shape
        if not isinstance(envelope, dict):
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=False,
                continuation_in=continuation,
                raw_response_refs=[parent_ref],
                page_error=ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    message="Response root is not a JSON object",
                ),
            )
        if "data" not in envelope:
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=False,
                continuation_in=continuation,
                raw_response_refs=[parent_ref],
                page_error=ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    message="Response envelope missing required 'data' key",
                    field_path="data",
                ),
            )
        data = envelope["data"]
        if not isinstance(data, list):
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=False,
                continuation_in=continuation,
                raw_response_refs=[parent_ref],
                page_error=ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    message="Response 'data' is not a JSON array",
                    field_path="data",
                ),
            )

        # Extract pagination metadata
        links = envelope.get("links")
        page_error: ClassifiedError | None = None
        continuation_out: Continuation | None = None
        exhausted = False

        if links is None or not isinstance(links, dict):
            page_error = ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                message="Response envelope missing or malformed 'links' object",
                field_path="links",
            )
            # Continue processing records; pagination state is unknown
        else:
            next_page, next_err = self._extract_next_page(links, current_page)
            if next_err is not None:
                page_error = next_err
                # Preserve valid records even when pagination metadata fails
            elif next_page is None:
                # links.next is explicitly null → terminal
                exhausted = True
            else:
                scope_id = self._source.inventory_scope.scope_id
                continuation_out = Continuation(
                    kind=CONTINUATION_KIND,
                    value=str(next_page),
                    source_key=config.source_key,
                    scope_id=scope_id,
                    adapter_name=ADAPTER_NAME,
                )

        # Process individual records
        items: list[RawPosting] = []
        issues: list[RecordIssue] = []

        for i, job in enumerate(data):
            record_index = i + 1  # 1-based as required by RecordIssue spec

            if not isinstance(job, dict):
                issues.append(
                    RecordIssue(
                        input_ref=parent_ref,
                        input_hash=parent_hash,
                        record_index=record_index,
                        field_path=f"data[{i}]",
                        code="invalid_record_type",
                        severity="error",
                        message=f"data[{i}] is not a JSON object; got {type(job).__name__}",
                        category=ErrorCategory.VALIDATION,
                    )
                )
                continue

            # Establish source identity
            source_key_result = self._build_source_key(
                job, record_index, parent_ref, parent_hash
            )
            if isinstance(source_key_result, RecordIssue):
                issues.append(source_key_result)
                continue
            source_key = source_key_result

            # Serialise and capture derived envelope (separate from parent bytes)
            try:
                env_bytes = self._serialize_envelope(
                    job, parent_ref, parent_hash, record_index
                )
                env_ref, env_hash = self._sink.capture(
                    env_bytes,
                    f"arbeitnow_env_{source_key.source_posting_id}",
                )
            except Exception as exc:
                issues.append(
                    RecordIssue(
                        input_ref=parent_ref,
                        input_hash=parent_hash,
                        record_index=record_index,
                        source_key=source_key,
                        field_path="capture",
                        code="envelope_capture_failed",
                        severity="error",
                        message="Failed to capture derived record envelope",
                        category=ErrorCategory.CAPACITY,
                    )
                )
                continue

            raw_posting = RawPosting(
                raw_payload_ref=env_ref,
                raw_content_hash=env_hash,
                source_key=source_key,
                fetch_time=fetch_time,
                raw_payload=env_bytes.decode("utf-8"),
            )
            items.append(raw_posting)

        return AdapterPage(
            items=items,
            issues=issues,
            raw_response_refs=[parent_ref],
            continuation_in=continuation,
            continuation_out=continuation_out,
            exhausted=exhausted,
            page_error=page_error,
        )

    # ── Adapter Protocol: draft_posting ───────────────────────────────────────

    def draft_posting(self, raw: RawPosting) -> DraftResult:
        """Map a C05 RawPosting into a DraftResult with SourceJobDraft.

        Parses the derived envelope from raw_payload, validates types,
        and calls the shared mapping helper.  Works after serialisation/reload.
        """
        raw_ref = raw.raw_payload_ref
        raw_hash = raw.raw_content_hash

        # ── Parse envelope ─────────────────────────────────────────────────────
        try:
            envelope = json.loads(raw.raw_payload)
        except (json.JSONDecodeError, ValueError):
            return DraftResult(
                raw_reference=raw_ref,
                draft=None,
                issues=[
                    RecordIssue(
                        input_ref=raw_ref,
                        input_hash=raw_hash,
                        field_path="raw_payload",
                        code="envelope_parse_error",
                        severity="error",
                        message="Cannot parse raw_payload as JSON; envelope may be corrupt",
                        category=ErrorCategory.VALIDATION,
                    )
                ],
            )

        if not isinstance(envelope, dict):
            return DraftResult(
                raw_reference=raw_ref,
                draft=None,
                issues=[
                    RecordIssue(
                        input_ref=raw_ref,
                        input_hash=raw_hash,
                        field_path="envelope",
                        code="invalid_envelope_type",
                        severity="error",
                        message="Parsed envelope is not a JSON object",
                        category=ErrorCategory.VALIDATION,
                    )
                ],
            )

        env_version = envelope.get("envelope_version")
        if env_version != ENVELOPE_VERSION:
            return DraftResult(
                raw_reference=raw_ref,
                draft=None,
                issues=[
                    RecordIssue(
                        input_ref=raw_ref,
                        input_hash=raw_hash,
                        field_path="envelope_version",
                        code="unsupported_envelope_version",
                        severity="error",
                        message=(
                            f"Unsupported envelope version '{env_version}'; "
                            f"expected '{ENVELOPE_VERSION}'"
                        ),
                        category=ErrorCategory.VALIDATION,
                    )
                ],
            )

        job = envelope.get("record")
        if not isinstance(job, dict):
            return DraftResult(
                raw_reference=raw_ref,
                draft=None,
                issues=[
                    RecordIssue(
                        input_ref=raw_ref,
                        input_hash=raw_hash,
                        field_path="record",
                        code="missing_or_invalid_record",
                        severity="error",
                        message="Envelope 'record' is missing or not a JSON object",
                        category=ErrorCategory.VALIDATION,
                    )
                ],
            )

        capture_meta = envelope.get("capture") or {}
        parent_ref = capture_meta.get("parent_ref", raw_ref)
        parent_hash_val = capture_meta.get("parent_hash", raw_hash)
        record_index = capture_meta.get("record_index")
        attribution = capture_meta.get("attribution") or {}

        # Deep-copy original provider fields (original_fields must not share mutable state)
        original_fields = copy.deepcopy(job)

        # ── Type-validated field translation for mapping helper ────────────────
        mapping_input: dict[str, Any] = {}
        issues: list[RecordIssue] = []

        def _issue(
            field: str, code: str, msg: str, severity: str = "error"
        ) -> None:
            issues.append(
                RecordIssue(
                    input_ref=raw_ref,
                    input_hash=raw_hash,
                    record_index=record_index,
                    source_key=raw.source_key,
                    field_path=field,
                    code=code,
                    severity=severity,
                    message=msg,
                    category=ErrorCategory.VALIDATION,
                )
            )

        # url → source_url (required by mapping helper)
        url_val = job.get("url")
        if "url" in job:
            if url_val is not None and not isinstance(url_val, str):
                _issue(
                    "url",
                    "invalid_url_type",
                    f"url must be a string, got {type(url_val).__name__}",
                )
            elif url_val is not None:
                mapping_input["source_url"] = url_val
            # Missing url → no source_url in mapping_input → helper returns blocking error

        # description (required by mapping helper; preserves HTML)
        desc_val = job.get("description")
        if "description" in job:
            if desc_val is not None and not isinstance(desc_val, str):
                _issue(
                    "description",
                    "invalid_description_type",
                    f"description must be a string, got {type(desc_val).__name__}",
                )
            elif desc_val is not None:
                mapping_input["description"] = desc_val  # Raw HTML preserved as-is
            # Empty string / None left out → helper returns missing_posting_text error

        # title (optional in C05; helper generates warning if missing)
        title_val = job.get("title")
        if "title" in job:
            if title_val is not None and not isinstance(title_val, str):
                _issue(
                    "title",
                    "invalid_title_type",
                    f"title must be a string, got {type(title_val).__name__}",
                )
            elif title_val is not None:
                mapping_input["title"] = title_val

        # company_name → company (helper checks "company" or "company_name_hint")
        cname_val = job.get("company_name")
        if "company_name" in job:
            if cname_val is not None and not isinstance(cname_val, str):
                _issue(
                    "company_name",
                    "invalid_company_name_type",
                    f"company_name must be a string, got {type(cname_val).__name__}",
                )
            elif cname_val is not None:
                mapping_input["company"] = cname_val

        # location → locations_raw (optional; preserve string as-is)
        loc_val = job.get("location")
        if "location" in job:
            if loc_val is not None and not isinstance(loc_val, str):
                _issue(
                    "location",
                    "invalid_location_type",
                    f"location must be a string, got {type(loc_val).__name__}",
                )
            elif loc_val is not None and loc_val.strip():
                mapping_input["locations_raw"] = loc_val

        # remote (must be boolean; not string "true"/"false", not integer)
        remote_key_present = "remote" in job
        remote_val = job.get("remote")
        remote_valid_type = True
        if remote_key_present:
            if remote_val is not None and not isinstance(remote_val, bool):
                _issue(
                    "remote",
                    "invalid_remote_type",
                    f"remote must be a boolean, got {type(remote_val).__name__}",
                )
                remote_valid_type = False

        # created_at: validate type; preserve in original_fields only (U05)
        cat_val = job.get("created_at")
        cat_key_present = "created_at" in job
        if cat_key_present and cat_val is not None:
            # bool is a subclass of int in Python — reject it explicitly
            if isinstance(cat_val, bool):
                _issue(
                    "created_at",
                    "invalid_created_at_type",
                    "created_at must be an integer, got bool",
                )
            elif isinstance(cat_val, float):
                _issue(
                    "created_at",
                    "invalid_created_at_type",
                    f"created_at must be an integer, got float ({cat_val!r})",
                )
            elif not isinstance(cat_val, int):
                _issue(
                    "created_at",
                    "invalid_created_at_type",
                    f"created_at must be an integer, got {type(cat_val).__name__}",
                )
            # Valid integer: already in original_fields; source_published_raw=None (U05)

        # source_published_raw stays None per U05 (created_at meaning unresolved)
        mapping_input["source_published_raw"] = None

        # job_types: validate container and member types
        jt_val = job.get("job_types")
        jt_key_present = "job_types" in job
        jt_valid = True
        if jt_key_present:
            if jt_val is not None and not isinstance(jt_val, list):
                _issue(
                    "job_types",
                    "invalid_job_types_type",
                    f"job_types must be an array, got {type(jt_val).__name__}",
                )
                jt_valid = False
            elif jt_val is not None:
                for idx, item in enumerate(jt_val):
                    if not isinstance(item, str):
                        _issue(
                            f"job_types[{idx}]",
                            "invalid_job_type_member",
                            f"job_types[{idx}] must be a string, got {type(item).__name__}",
                        )
                        jt_valid = False
                        break

        # Return early if blocking type errors exist
        if any(iss.severity == "error" for iss in issues):
            return DraftResult(raw_reference=raw_ref, draft=None, issues=issues)

        # ── Call shared mapping helper ─────────────────────────────────────────
        try:
            mapped_fields, helper_issues = map_raw_record_to_draft_fields(
                raw_data=mapping_input,
                input_ref=raw_ref,
                input_hash=raw_hash,
                record_index=record_index,
                source_key=raw.source_key,
            )
        except Exception as exc:
            _issue("mapping", "mapping_helper_error", f"Mapping helper raised: {type(exc).__name__}")
            return DraftResult(raw_reference=raw_ref, draft=None, issues=issues)

        issues.extend(helper_issues)

        # ── Post-helper: inject provider-specific fields the helper cannot handle ──
        # remote: boolean cannot survive the helper's str() coercion; set directly
        if remote_key_present and remote_valid_type:
            mapped_fields["workplace_type_raw"] = remote_val
        else:
            mapped_fields.setdefault("workplace_type_raw", None)

        # job_types: list cannot survive the helper; set directly
        if jt_key_present and jt_valid:
            if jt_val is None:
                mapped_fields["employment_type_raw"] = None
            else:
                mapped_fields["employment_type_raw"] = list(jt_val)  # copy
        else:
            mapped_fields.setdefault("employment_type_raw", None)

        # No compensation, deadline, or application_url from this source
        mapped_fields.setdefault("compensation_raw", None)
        mapped_fields.setdefault("source_deadline_raw", None)
        mapped_fields.setdefault("application_url", None)

        # Attribution metadata (provider-local; not a new top-level C05 field per U09)
        mapped_fields["attribution"] = {
            "notice": attribution.get("notice", ATTRIBUTION_NOTICE),
            "link": attribution.get("link", ATTRIBUTION_LINK),
        }
        # Overwrite mapping_version with adapter-specific ID
        mapped_fields["mapping_version"] = MAPPING_ID

        # Check for blocking errors after helper
        if any(iss.severity == "error" for iss in issues):
            return DraftResult(raw_reference=raw_ref, draft=None, issues=issues)

        draft = SourceJobDraft(
            raw_reference=raw_ref,
            source_key=raw.source_key,
            fetch_time=raw.fetch_time,
            original_fields=original_fields,
            source_mapped_fields=mapped_fields,
        )
        return DraftResult(raw_reference=raw_ref, draft=draft, issues=issues)

