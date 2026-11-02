"""Generate positive and negative synthetic fixtures for C01–C15."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent

FIXTURES = {
    "C01": {
        "valid.json": {
            "schema_version": "1.0",
            "candidate_id": "11111111-1111-4111-8111-111111111111",
            "profile_version": "v2026.1",
            "approval_metadata": {
                "schema_version": "1.0",
                "is_approved": True,
                "approved_by": "candidate_self",
                "approved_at": "2026-10-27T10:00:00+00:00",
                "notes": "Verified initial profile"
            },
            "explicit_eligibility": {
                "schema_version": "1.0",
                "work_authorization_countries": ["DE", "AT"],
                "target_locations": ["Berlin", "Remote"],
                "remote_eligible": True,
                "min_salary": {
                    "schema_version": "1.0",
                    "amount": "65000.00",
                    "currency": "EUR"
                },
                "language_proficiencies": {
                    "de": "C1",
                    "en": "C2"
                }
            },
            "evidence_records": [
                {
                    "schema_version": "1.0",
                    "fact_id": "22222222-2222-4222-8222-222222222222",
                    "kind": "employment",
                    "parent_id": None,
                    "title": "Senior Python Developer",
                    "organization": "Tech GmbH",
                    "start_date": {
                        "schema_version": "1.0",
                        "value": "2021-05",
                        "precision": "month"
                    },
                    "end_date": None,
                    "claims": ["Developed backend data pipelines"],
                    "skills": ["Python", "Docker", "PostgreSQL"],
                    "metrics": ["Scaled ingestion to 50k events/sec"],
                    "provenance": "employment_contract_2021.pdf",
                    "allowed_uses": ["cv", "cover_letter", "assessment"]
                }
            ]
        },
        "invalid.json": {
            "schema_version": "1.0",
            "candidate_id": "not-a-uuid",
            "profile_version": "v1"
        }
    },
    "C02": {
        "valid.json": {
            "schema_version": "1.0",
            "policy_version": "pol-de-v1",
            "regions": ["DE"],
            "role_aliases": {
                "Software Engineer": ["Backend Developer", "Python Engineer"]
            },
            "skill_aliases": {
                "Python": ["Python3", "FastAPI"]
            },
            "hard_criteria": [
                {
                    "schema_version": "1.0",
                    "criterion_id": "crit_location",
                    "name": "Location Germany or Remote",
                    "field": "workplace_type",
                    "operator": "in",
                    "expected_value": ["remote", "hybrid", "onsite"],
                    "on_missing": "unknown"
                }
            ],
            "preferences": [
                {
                    "schema_version": "1.0",
                    "rule_id": "pref_python",
                    "name": "Python backend focus",
                    "field": "skills",
                    "weight": 0.8,
                    "preferred_values": ["Python"]
                }
            ],
            "exclusions": ["Gambling"],
            "missing_information_behavior": {
                "compensation": "unknown"
            },
            "relevance_configuration": {
                "schema_version": "1.0",
                "score_scale": "0-100",
                "min_score_threshold": 70.0,
                "broad_keywords": ["Python", "Backend"],
                "negative_keywords": ["Unpaid"]
            },
            "primary_context_strategy": "json"
        },
        "invalid.json": {
            "schema_version": "1.0",
            "policy_version": "pol-1",
            "primary_context_strategy": "automatic-agent"
        }
    },
    "C03": {
        "valid.json": {
            "schema_version": "1.0",
            "source_key": "arbeitnow_de",
            "provider": "arbeitnow",
            "board_id": "default",
            "acquisition_method": "api",
            "base_url": "https://job-board-api.com/api/v1/jobs",
            "access_rules": "Max 1 req/sec",
            "attribution_rules": "Attribution to Arbeitnow API",
            "request_policy": {"timeout": 30},
            "enabled": False,
            "inventory_semantics": "filtered_feed"
        },
        "invalid.json": {
            "schema_version": "1.0",
            "source_key": "test",
            "acquisition_method": "unsupported_scraping"
        }
    },
    "C04": {
        "valid.json": {
            "schema_version": "1.0",
            "run_id": "33333333-3333-4333-8333-333333333333",
            "source_key": "arbeitnow_de",
            "scope_id": "tech-jobs",
            "start_time": "2026-10-27T10:00:00+00:00",
            "end_time": "2026-10-27T10:02:00+00:00",
            "cursor_in": None,
            "cursor_out": "page_2",
            "page_count": 1,
            "raw_response_refs": ["raw/run_1_page_1.json"],
            "observed_posting_identities": ["post-101", "post-102"],
            "outcome": "complete",
            "inventory_semantics": "filtered_feed",
            "error": None
        },
        "invalid.json": {
            "schema_version": "1.0",
            "run_id": "33333333-3333-4333-8333-333333333333",
            "page_count": -5
        }
    },
    "C05": {
        "valid.json": {
            "schema_version": "1.0",
            "raw_payload_ref": "raw/snapshots/101.json",
            "raw_content_hash": "sha256:" + "a" * 64,
            "source_key": {
                "schema_version": "1.0",
                "provider": "arbeitnow",
                "board_id": "default",
                "source_posting_id": "101"
            },
            "fetch_time": "2026-10-27T10:00:00+00:00",
            "raw_headers": {"content-type": "application/json"},
            "raw_payload": '{"id": 101, "role": "Python Dev", "location": "Berlin"}'
        },
        "invalid.json": {
            "schema_version": "1.0",
            "raw_payload_ref": "raw/101.json",
            "raw_content_hash": "invalid-hash-format"
        }
    },
    "C06": {
        "valid.json": {
            "schema_version": "1.0",
            "source_key": {
                "schema_version": "1.0",
                "provider": "arbeitnow",
                "board_id": "default",
                "source_posting_id": "101"
            },
            "normalizer_version": "1.0",
            "raw_reference": "raw/snapshots/101.json",
            "raw_content_hash": "sha256:" + "a" * 64,
            "company_name_hint": "Tech Corp GmbH",
            "company_id_hint": None,
            "title": "Senior Python Backend Engineer",
            "description_clean": "Join our platform team to build scalable Python services.",
            "source_url": "https://example.com/jobs/101",
            "application_url": "https://example.com/jobs/101/apply",
            "locations": [
                {
                    "schema_version": "1.0",
                    "raw_text": "Berlin, Germany",
                    "country": "DE",
                    "region": "Berlin",
                    "city": "Berlin",
                    "postal_code": "10115"
                }
            ],
            "workplace_type": "remote",
            "remote_eligibility_restrictions": ["DE"],
            "employment_type": "full_time",
            "compensation": {
                "schema_version": "1.0",
                "min_amount": "70000.00",
                "max_amount": "90000.00",
                "currency": "EUR",
                "period": "yearly",
                "is_gross": True,
                "provenance": "employer_provided"
            },
            "advert_language": "de",
            "source_published_at": "2026-10-26T14:00:00+00:00",
            "source_updated_at": None,
            "source_deadline_at": None,
            "observed_at": "2026-10-27T10:00:00+00:00",
            "field_provenance": {"title": "raw.role"}
        },
        "invalid.json": {
            "schema_version": "1.0",
            "source_key": {
                "schema_version": "1.0",
                "provider": "arbeitnow",
                "board_id": "default",
                "source_posting_id": "101"
            },
            "title": "",
            "description_clean": "Description without normalizer version"
        }
    },
    "C07": {
        "valid.json": {
            "schema_version": "1.0",
            "canonical_job_id": "44444444-4444-4444-8444-444444444444",
            "canonical_company_id": "55555555-5555-4555-8555-555555555555",
            "company_name": "Tech Corp GmbH",
            "linked_source_keys": [
                {
                    "schema_version": "1.0",
                    "provider": "arbeitnow",
                    "board_id": "default",
                    "source_posting_id": "101"
                }
            ],
            "revisions": [
                {
                    "schema_version": "1.0",
                    "revision_id": "66666666-6666-4666-8666-666666666666",
                    "canonical_job_id": "44444444-4444-4444-8444-444444444444",
                    "source_key": {
                        "schema_version": "1.0",
                        "provider": "arbeitnow",
                        "board_id": "default",
                        "source_posting_id": "101"
                    },
                    "content_hash": "sha256:" + "b" * 64,
                    "title": "Senior Python Backend Engineer",
                    "first_seen_at": "2026-10-27T10:00:00+00:00",
                    "last_seen_at": "2026-10-27T10:00:00+00:00",
                    "source_urls": ["https://example.com/jobs/101"],
                    "application_urls": ["https://example.com/jobs/101/apply"],
                    "availability": "active"
                }
            ],
            "current_revision_id": "66666666-6666-4666-8666-666666666666",
            "first_seen_at": "2026-10-27T10:00:00+00:00",
            "last_seen_at": "2026-10-27T10:00:00+00:00",
            "availability": "active",
            "merge_lineage": ["initial_registration"]
        },
        "invalid.json": {
            "schema_version": "1.0",
            "canonical_job_id": "not-a-uuid",
            "company_name": ""
        }
    },
    "C08": {
        "valid.json": {
            "schema_version": "1.0",
            "source_kind": "candidate",
            "profile_version": "v2026.1",
            "fact_id": "22222222-2222-4222-8222-222222222222"
        },
        "invalid.json": {
            "schema_version": "1.0",
            "source_kind": "candidate",
            "fact_id": "22222222-2222-4222-8222-222222222222"
        }
    },
    "C09": {
        "valid.json": {
            "schema_version": "1.0",
            "strategy": "json",
            "profile_version": "v2026.1",
            "posting_revision": "sha256:" + "b" * 64,
            "ordered_facts": [],
            "mandatory_context": ["Work auth: DE"],
            "selected_fact_ids": ["22222222-2222-4222-8222-222222222222"],
            "token_budget": 4000,
            "estimated_tokens": 1200,
            "warnings": []
        },
        "invalid.json": {
            "schema_version": "1.0",
            "strategy": "json",
            "token_budget": -100
        }
    },
    "C10": {
        "valid.json": {
            "schema_version": "1.0",
            "call_id": "77777777-7777-4777-8777-777777777777",
            "operation_type": "relevance_assessment",
            "model_identifier": "llama3:8b-instruct-q4_K_M",
            "model_digest": None,
            "prompt_version": "assess_v1",
            "system_prompt_version": None,
            "generation_settings": {"temperature": 0.1},
            "context_limit": 8192,
            "input_fingerprint": "sha256:" + "c" * 64,
            "requested_schema": "C11_assessment"
        },
        "invalid.json": {
            "schema_version": "1.0",
            "call_id": "77777777-7777-4777-8777-777777777777",
            "context_limit": 0
        }
    },
    "C11": {
        "valid.json": {
            "schema_version": "1.0",
            "assessment_id": "88888888-8888-4888-8888-888888888888",
            "canonical_job_id": "44444444-4444-4444-8444-444444444444",
            "posting_revision": "sha256:" + "b" * 64,
            "profile_version": "v2026.1",
            "policy_version": "pol-de-v1",
            "assessment_method": "rules",
            "rule_outcomes": [
                {
                    "schema_version": "1.0",
                    "criterion_id": "crit_location",
                    "criterion_name": "Location Check",
                    "result": "pass",
                    "reason": "Remote in DE matches criteria"
                }
            ],
            "relevance_decision": "eligible",
            "relevance_score": None,
            "score_scale": None,
            "identified_gaps": [],
            "identified_unknowns": [],
            "summary_reason": "Hard rules satisfied",
            "final_disposition": "eligible",
            "model_metadata": None
        },
        "invalid.json": {
            "schema_version": "1.0",
            "assessment_id": "88888888-8888-4888-8888-888888888888",
            "assessment_method": "llm",
            "final_disposition": "eligible"
        }
    },
    "C12": {
        "valid.json": {
            "schema_version": "1.0",
            "operation_id": "99999999-9999-4999-8999-999999999999",
            "canonical_job_id": "44444444-4444-4444-8444-444444444444",
            "payload_version": "2026-10-27T10:00:00Z",
            "payload_fingerprint": "sha256:" + "d" * 64,
            "locally_owned_payload": {
                "schema_version": "1.0",
                "canonical_job_id": "44444444-4444-4444-8444-444444444444",
                "job_title": "Senior Python Backend Engineer",
                "company_name": "Tech Corp GmbH",
                "availability": "active",
                "assessment_disposition": "eligible",
                "relevance_score": 85.0,
                "score_scale": "0-100",
                "assessment_reasons": "Hard rules satisfied",
                "source_urls": ["https://example.com/jobs/101"],
                "last_evaluated_at": "2026-10-27T10:00:00+00:00"
            },
            "attempt_count": 0,
            "max_attempts": 3,
            "state": "pending",
            "remote_record_id": None,
            "remote_acknowledged_at": None,
            "error": None
        },
        "invalid.json": {
            "schema_version": "1.0",
            "operation_id": "99999999-9999-4999-8999-999999999999",
            "max_attempts": 0
        }
    },
    "C13": {
        "valid.json": {
            "schema_version": "1.0",
            "request_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "salesforce_request_id": None,
            "client_request_key": None,
            "canonical_job_id": "44444444-4444-4444-8444-444444444444",
            "document_type": "cv",
            "target_language": "de",
            "template_id": "modern_de_v1",
            "context_strategy": "json",
            "allow_unavailable_job": False,
            "state": "pending",
            "created_at": "2026-10-27T10:00:00+00:00",
            "claimed_at": None,
            "completed_at": None,
            "frozen_input_versions": None,
            "predecessor_request_id": None,
            "result_artifact_ref": None,
            "error": None
        },
        "invalid.json": {
            "schema_version": "1.0",
            "request_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "canonical_job_id": "44444444-4444-4444-8444-444444444444",
            "document_type": "cv",
            "template_id": "modern_de_v1",
            "state": "running"
        }
    },
    "C14": {
        "valid.json": {
            "schema_version": "1.0",
            "artifact_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "request_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "artifact_version": 1,
            "format": "docx",
            "local_path": "C:\\Users\\Example\\Job Automation Daten\\artifacts\\CV.docx",
            "content_hash": "sha256:" + "e" * 64,
            "size_bytes": 45000,
            "remote_file_id": None,
            "delivery_status": "local_only",
            "approval_status": "draft",
            "reconciliation_marker": "req-aaa-v1",
            "created_at": "2026-10-27T10:00:00+00:00"
        },
        "invalid.json": {
            "schema_version": "1.0",
            "artifact_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "format": "txt",
            "size_bytes": -5
        }
    },
    "C15": {
        "valid.json": {
            "schema_version": "1.0",
            "run_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "start_time": "2026-10-27T10:00:00+00:00",
            "end_time": "2026-10-27T10:05:00+00:00",
            "status": "success",
            "source_counts": {"arbeitnow_de": 3},
            "source_postings_count": 3,
            "canonical_jobs_new": 2,
            "canonical_jobs_updated": 0,
            "canonical_jobs_duplicate": 1,
            "eligible_count": 1,
            "review_count": 1,
            "rejected_count": 0,
            "sync_operations_succeeded": 2,
            "sync_operations_failed": 0,
            "errors": [],
            "pending_work": []
        },
        "invalid.json": {
            "schema_version": "1.0",
            "run_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "source_postings_count": -1
        }
    }
}


def write_fixtures() -> None:
    for contract_dir, files in FIXTURES.items():
        target_dir = FIXTURES_DIR / contract_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in files.items():
            dest = target_dir / filename
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2, ensure_ascii=False)
                f.write("\n")
    print("All fixtures generated successfully.")


if __name__ == "__main__":
    write_fixtures()

