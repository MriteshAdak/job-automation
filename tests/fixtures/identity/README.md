# IDENTITY-01 Test Fixtures and Scenarios

This directory documents the synthetic test corpus and scenarios for **IDENTITY-01** (Company/job identity and revisions).

## Scenarios Covered

1. **Repeated Postings (`exact_source_same_content`)**:
   - Re-observation of the exact same source tuple `(provider, board_id, source_posting_id)` with identical normalized content.
   - Reuses canonical job UUID and posting revision UUID.
   - Advances `last_seen_at` without generating a duplicate record.

2. **Changed Descriptions (`exact_source_new_revision`)**:
   - Re-observation of the same source tuple with edited title, description, or compensation.
   - Reuses canonical job UUID.
   - Allocates a new revision UUID under the parent job; historical revision remains resolvable.

3. **Different Boards with Identical Source IDs**:
   - Distinct source keys such as `("arbeitnow", "board_a", "101")` and `("arbeitnow", "board_b", "101")`.
   - Distinct source key namespaces ensure these remain completely separate canonical opportunities.

4. **Distinct Requisitions (`differing_requisitions`)**:
   - Postings from the same employer with identical title and description, but differing explicit requisition identifiers.
   - Strong conflict rule strictly prevents auto-merging.

5. **Cross-Source Strong Matching (`strong_key_match`)**:
   - Two different source postings with matching requisition numbers or matching job-specific application URLs under the same employer.
   - Linked as alternate sources under the same canonical job.

6. **Fuzzy Text Similarity Review (`review_candidate`)**:
   - High similarity in title and description across different sources without strong keys.
   - Treated strictly as review candidates, never auto-merged.
   - Bounded review cases are created for human inspection.

7. **Reversible Merge and Reversal (`merge` & `reversal`)**:
   - Merging Job A and Job B groups their sources and revisions under surviving Job A.
   - Reversing the merge restores Job B with its original UUID, original sources, and all linked revisions (including those observed during the merge period).

