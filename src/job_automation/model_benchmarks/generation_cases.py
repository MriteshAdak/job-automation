"""Reproducible input cases for generation benchmarks (MODEL-02-S03).

Enforces:
- Attributable, static prompt text across models for apples-to-apples comparison.
- Scaled token budgets: short (~200 tokens), medium (~800 tokens), near-budget (~1700 tokens), and overflow (>2048 tokens).
- Bilingual coverage (English & German technical and office roles) honoring R07 and R13.
- Standardized registered schema target ("C11_assessment").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GenerationTestCase:
    """Pre-rendered benchmark test case."""

    case_id: str
    description: str
    system_prompt: str
    user_prompt: str
    target_schema: str = "C11_assessment"
    estimated_tokens: int = 250


SHORT_SYSTEM_PROMPT = (
    "You are an expert AI recruiting assistant evaluating candidate fit for job postings. "
    "Respond strictly with valid JSON conforming to the requested schema. No code fences, no extra commentary."
)

SHORT_USER_PROMPT = (
    "Evaluate candidate Max Mustermann for Job Posting 'Senior Python Developer' in Berlin (German/English).\n"
    "Candidate profile:\n"
    "- 6 years backend engineering with Python 3, FastAPI, PostgreSQL, Docker, AWS.\n"
    "- Professional proficiency in English (C1) and German (B2).\n"
    "Job requirements:\n"
    "1. At least 4 years Python backend experience.\n"
    "2. Experience with relational databases (PostgreSQL).\n"
    "3. Fluent English communication.\n"
    "Provide a full assessment with relevance_decision 'eligible', score 90.0, score_scale '0-100', "
    "final_disposition 'eligible', assessment_method 'rules', profile_version 'v1', policy_version 'v1', "
    "posting_revision 'rev1', assessment_id '11111111-1111-4111-8111-111111111111', "
    "canonical_job_id '22222222-2222-4222-8222-222222222222', summary_reason 'Strong alignment with core requirements.'"
)

MEDIUM_USER_PROMPT = (
    "Evaluate candidate Dr. Sarah Weber for Job Posting 'Lead Data Platform Engineer / Architekt (m/w/d)' in München.\n\n"
    "Unternehmensprofil & Aufgabenstellung:\n"
    "Wir suchen eine führungsstarke Persönlichkeit zur Weiterentwicklung unserer Cloud-Data-Plattform. "
    "Sie konzipieren skalierbare ETL/ELT-Pipelines, etablieren Data-Governance-Richtlinien und leiten ein Team "
    "von 5 Data Engineers. Einsatz moderner Technologien: Apache Spark, Snowflake, dbt, Kubernetes und Terraform.\n\n"
    "Kandidatenprofil (Dr. Sarah Weber):\n"
    "- Promotion in Informatik an der TU München mit Schwerpunkt verteilte Systeme.\n"
    "- 8 Jahre relevante Berufserfahrung im Bereich Big Data Architecture und Distributed Data Processing.\n"
    "- Tiefgehende Praxiserfahrung mit Apache Spark, PySpark, Databricks, PostgreSQL und BigQuery.\n"
    "- Fundierte Kenntnisse in Cloud-Infrastruktur: AWS (EKS, S3, IAM) und GCP.\n"
    "- 3 Jahre disziplinarische und fachliche Teamleitung (agile Methoden, Scrum, OKRs).\n"
    "- Sprachen: Deutsch (Muttersprache), Englisch (verhandlungssicher in Wort und Schrift).\n\n"
    "Anforderungskatalog:\n"
    "REQ-01: Abgeschlossenes Studium (Master/Promotion) der Informatik oder vergleichbar.\n"
    "REQ-02: Mindestens 5 Jahre Erfahrung im Aufbau moderner Datenplattformen (Spark, Cloud DWH).\n"
    "REQ-03: Nachweisbare Führungserfahrung in cross-funktionalen Data-Teams.\n"
    "REQ-04: Verhandlungssichere Deutsch- und Englischkenntnisse in Wort und Schrift.\n\n"
    "Bitte erstellen Sie das strukturierte C11_assessment mit relevance_decision 'eligible', relevance_score 95.0, "
    "score_scale '0-100', final_disposition 'eligible', summary_reason 'Hervorragende fachliche und methodische Eignung.', "
    "assessment_id '33333333-3333-4333-8333-333333333333', canonical_job_id '44444444-4444-4444-8444-444444444444', "
    "posting_revision 'rev-muc-01', profile_version 'p-weber-v1', policy_version 'pol-de-v1', assessment_method 'rules'."
)

# Near-budget prompt repeating detailed context facts to simulate 1600+ tokens
NEAR_BUDGET_FACTS = """
Detailed Candidate Work History & Skills Catalog:
- Position: Senior Infrastructure Architect at CloudScale AG (2020-2026)
  Led the migration of 45 on-premise microservices to Kubernetes on AWS and GCP. Designed zero-trust IAM architecture,
  reduced cloud infrastructure spending by 28% through reserved instance planning and auto-scaling optimizations.
  Implemented CI/CD pipelines using GitHub Actions, ArgoCD, Terraform, and Vault. Monitored reliability with Prometheus,
  Grafana, and OpenTelemetry. Mentored junior and mid-level engineers, conducted technical interviews.
- Position: Systems Engineer at DataHub GmbH (2016-2020)
  Maintained Linux production servers (Ubuntu, RHEL), automated deployment scripts using Ansible and Python. Managed
  large PostgreSQL cluster replication, pg_dump backups, point-in-time recovery testing, and database indexing optimizations.
  Configured network load balancers, SSL certificates, NGINX reverse proxies, and failover topologies.
- Skills: Python, Go, Bash, C++, Rust, PostgreSQL, Redis, Elasticsearch, Docker, Kubernetes, Helm, Terraform, AWS, Azure, GCP.
- Soft Skills & Leadership: Technical project management, cross-department communication, crisis incident response management.
"""

NEAR_BUDGET_USER_PROMPT = (
    MEDIUM_USER_PROMPT + "\n\n" + (NEAR_BUDGET_FACTS * 4) + "\n\n"
    "Synthesize all evidence thoroughly and output valid C11_assessment JSON."
)

OVERFLOW_USER_PROMPT = (
    MEDIUM_USER_PROMPT + "\n\n" + (NEAR_BUDGET_FACTS * 10) + "\n\n"
    "Evaluate complete exhaustive history exceeding 2048 context limit."
)


GENERATION_CASES: dict[str, GenerationTestCase] = {
    "case_gen_short": GenerationTestCase(
        case_id="case_gen_short",
        description="Short assessment evaluation (~200 tokens)",
        system_prompt=SHORT_SYSTEM_PROMPT,
        user_prompt=SHORT_USER_PROMPT,
        estimated_tokens=220,
    ),
    "case_gen_medium": GenerationTestCase(
        case_id="case_gen_medium",
        description="Medium bilingual assessment evaluation (~750 tokens)",
        system_prompt=SHORT_SYSTEM_PROMPT,
        user_prompt=MEDIUM_USER_PROMPT,
        estimated_tokens=750,
    ),
    "case_gen_near_budget": GenerationTestCase(
        case_id="case_gen_near_budget",
        description="Near-budget assessment evaluation (~1700 tokens for 2048 ctx)",
        system_prompt=SHORT_SYSTEM_PROMPT,
        user_prompt=NEAR_BUDGET_USER_PROMPT,
        estimated_tokens=1750,
    ),
    "case_gen_overflow": GenerationTestCase(
        case_id="case_gen_overflow",
        description="Deliberate overflow probe (>2200 tokens for 2048 ctx budget test)",
        system_prompt=SHORT_SYSTEM_PROMPT,
        user_prompt=OVERFLOW_USER_PROMPT,
        estimated_tokens=2500,
    ),
}


def get_generation_case(case_id: str) -> GenerationTestCase:
    """Retrieve test case by ID or raise KeyError."""
    if case_id not in GENERATION_CASES:
        raise KeyError(f"Unknown generation case ID '{case_id}'")
    return GENERATION_CASES[case_id]

