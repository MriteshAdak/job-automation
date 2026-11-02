# POLICY-01 Synthetic Policy Fixture Catalog

This directory contains synthetic search policy fixtures for testing POLICY-01.
None of these fixtures represent actual candidate facts, live job postings, or real user preferences.

## Fixture Inventory

1. `valid_tech.json`: Synthetically valid technical search policy (Python, Software Engineer, remote/hybrid).
2. `valid_office.json`: Synthetically valid office/management search policy (Projektmanager, Scrum, full-time).
3. `invalid_duplicate_key.json`: Malformed JSON containing duplicate keys at the same object level.
4. `invalid_duplicate_rule_id.json`: Search policy with colliding criterion_id / rule_id identifiers.
5. `invalid_ambiguous_alias.json`: Alias mapped to multiple canonical roles within the same namespace.
6. `invalid_alias_chain.json`: Transitive alias chain where an alias is also declared as a canonical term.
7. `invalid_candidate_field.json`: Hard criterion targeting candidate facts (`candidate.language_proficiencies`).
8. `invalid_unsupported_target.json`: Criterion targeting unsupported field (`skills`).
9. `invalid_unsupported_schema.json`: Policy declaring an unsupported schema version (`2.0`).
10. `invalid_bare_salary.json`: Salary criterion using an ambiguous bare number without currency/period.
11. `invalid_contradictory_hard.json`: Mutually exclusive hard criteria on scalar field (`workplace_type`).
12. `invalid_exclusion_conflict.json`: Hard criterion requiring a role alias that is explicitly excluded.
13. `warning_unreachable_preference.json`: Valid policy with an unreachable soft preference (triggers warning).

