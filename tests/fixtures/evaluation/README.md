# Evaluation Fixtures Catalog (EVAL-01-S01, S02)

This directory contains synthetic, non-sensitive fixtures for evaluating JSON vs RAG matching, evidence retrieval, and disposition accuracy.

## Directory Layout

- `matching/`: Synthetic job postings representing diverse white-collar scenarios in Germany:
  - English and German language postings.
  - Complex multi-requirement postings with required vs preferred distinctions.
  - Semantic aliases (e.g., 'TypeScript frontend engineer' requiring 'React / Redux' without keyword matching 'Angular').
  - Tech distinctions: C# vs C++ vs .NET core.
  - Hard failure cases: strictly ineligible location, missing required work authorization, forbidden industry.
  - Hostile prompt injection / instruction attempts within job description.
  - Low-score / weak alignment postings.
- `evidence/`: Ground truth requirement annotations and evidence mappings:
  - Source spans in posting text.
  - Sufficient candidate fact ID sets (including multi-fact conjunctions).
  - Contradictory evidence references.
  - Unknown / missing evidence definitions.
- `profiles/`: Candidate profile snapshots containing:
  - Approved candidate facts with specific allowed purposes (`assessment`, `cv`).
  - Restricted facts (e.g. `cv` only) that must NOT be admitted or cited for assessment.
  - Explicit eligibility facts (work authorization, language proficiencies, target countries).
- `policies/`: Search policies with explicit hard rules, soft preferences, and missing data behavior.

## Guarantees

- Zero real candidate data or credentials.
- All candidate fact IDs exist in the corresponding synthetic profile snapshots.
- All source spans reference exact substrings of the synthetic postings.
- Zero publication side effects.

