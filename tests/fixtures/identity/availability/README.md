# Test Fixtures: IDENTITY-02 Availability Tracking

This directory documents synthetic scenarios and test fixtures used to verify posting availability and canonical aggregation according to the [IDENTITY-02](../../../docs/stories/IDENTITY-02.md) specification.

## Scenarios Covered

1. **Manifest Decision Matrix**:
   - `COMPLETE + COMPLETE_BOARD`: Authoritative full inventory. Qualifies for both positive sightings and negative disappearance inference.
   - `COMPLETE + SEARCH_RESULTS`: Search-only feed. Qualifies for positive sightings; strictly blocks negative disappearance inference (zero misses, even if empty).
   - `COMPLETE + FILTERED_FEED`: Filtered subset. Qualifies for positive sightings; blocks negative disappearance inference.
   - `PARTIAL`: Incomplete pagination, limit hit, or recoverable error. Positive sightings processed; negative inference blocked.
   - `FAILED`: Unsuccessful fetch. No negative inference; valid independent observations consumed separately.

2. **Scoped Baseline Enrollment**:
   - A posting observed in scope $S_1$ is enrolled solely in the baseline for $S_1$.
   - A subsequent complete fetch of scope $S_2$ does NOT evaluate absence for postings that only exist in $S_1$.
   - A posting first observed after a fetch's `start_time` is excluded from that fetch's absence set.

3. **Repeated Misses and Grace Conjunction**:
   - Default: `consecutive_complete_misses = 3`, `grace_seconds = 172800.0` (48 hours).
   - First miss: transitions to `not_seen`, sets `miss_count = 1`, records `missing_since = inventory_end`.
   - Closure to `unavailable` requires BOTH conditions met simultaneously.
   - High miss count without grace elapsed remains `not_seen`.
   - Long elapsed time with fewer than required misses remains `not_seen`.
   - Newer positive sighting resets streak to `active` with `miss_count = 0`.
   - Older/cached observations delivered out-of-order cannot reopen or reset an active streak.

4. **Multi-Source Canonical Aggregation**:
   - Rule 1: Any source `active` -> Canonical `active`.
   - Rule 2: Else any source `not_seen` -> Canonical `not_seen`.
   - Rule 3: Else any source `unknown` or no sources -> Canonical `unknown`.
   - Rule 4: All sources `unavailable` -> Canonical `unavailable`.

5. **State Separation and Candidate Protection**:
   - Machine-owned posting availability (`active`, `not_seen`, `unavailable`, `unknown`) is strictly decoupled from candidate application progress (`Applied`, `Interviewing`, `Offer`, etc.).
   - Transitioning a posting to `unavailable` or `active` NEVER modifies candidate application progress, candidate notes, or C11 assessment results.

