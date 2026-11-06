This is purely vibe-coded using just a high-level SPEC sheet (used to create component level story points for implementation) just to gauge Astra's default capability. This is being evaluated while a leaner and effective version is in development.

Models nowadays come with "You are a Senior/Principal/Staff Engineer" within their system prompt or training I guess.

# Job Automation

A job-search and application-preparation system built around a local Python pipeline and a Salesforce workspace. It collects job postings, evaluates them against candidate experience and search preferences, tracks opportunities, and prepares tailored CVs and cover letters for human review.

The application targets native Windows with Python 3.12+. SQLite stores local state, Ollama provides local model inference, and Salesforce provides the tracking and review interface. Documents are rendered as DOCX, with LibreOffice used for PDF conversion.

The main workflow is:

1. Import postings from configured sources or manual files.
2. Normalize postings, resolve duplicate jobs, and track revisions and availability.
3. Apply eligibility rules and, optionally, model-assisted relevance assessment.
4. Synchronize results to Salesforce for tracking and candidate decisions.
5. Process requested or opt-in automatic drafts, validate them against candidate evidence, and deliver them for human review and approval.

The components have the following roles:

| Component | Role in the system |
| --- | --- |
| [Profiles](src/job_automation/profile/) | Maintain approved candidate facts and evidence used for matching and drafting. |
| [Search policy](src/job_automation/policy/) | Define eligibility criteria, preferences, and shared search vocabulary. |
| [Sources](src/job_automation/sources/) | Manage source configuration and access rules, including manual CSV/text imports and the Arbeitnow API adapter. |
| [Ingestion](src/job_automation/ingestion/) | Fetch, capture, normalize, and validate postings before further processing. |
| [Identity](src/job_automation/identity/) | Resolve company and job identities, deduplicate postings, and track revisions and availability. |
| [Assessment](src/job_automation/assessment/) | Evaluate eligibility and relevance using deterministic rules and optional local models. |
| [Context](src/job_automation/context/) | Select candidate evidence through full-profile JSON or combined keyword and vector retrieval. |
| [Models](src/job_automation/models/) | Manage local model access, health checks, structured inference, and embeddings. |
| [Generation](src/job_automation/generation/) | Coordinate draft requests, freeze source evidence, generate and validate content, render documents, and deliver drafts. |
| [Salesforce integration](src/job_automation/salesforce/) | Handle authentication, API access, reliable synchronization, file delivery, and portability. |
| [Salesforce workspace](salesforce/) | Define tracking objects, views, generation actions, document review, permissions, and notifications. |
| [Orchestration](src/job_automation/orchestration/) | Coordinate pipeline stages, checkpoints, recovery, and run-summary delivery. |
| [Storage](src/job_automation/storage/) | Persist jobs, assessments, work queues, and run history in SQLite, with raw data and artifacts stored on disk. |
| [Contracts](src/job_automation/contracts/) and [schemas](schemas/) | Define shared, versioned data structures and validation boundaries between components. |
| [Operations](src/job_automation/operations/) | Support Windows scheduling, model supervision, retention, backups, and restore workflows. |
| [Evaluation](src/job_automation/evaluation/) and [benchmarks](src/job_automation/model_benchmarks/) | Compare assessment quality, context strategies, model choices, and runtime performance. |

The supporting directories provide configuration, tooling, and documentation:

- [config/](config/) — example settings for the application, sources, policies, models, Salesforce, and automation.
- [scripts/](scripts/) — model diagnostics, benchmarks, Salesforce metadata utilities, and Windows administration scripts.
- [tests/](tests/) — automated tests, fixtures, and manual verification tools.
- [docs/components/](docs/components/) — component handoffs, implementation details, verification status, and remaining integration checks.
- [docs/stories/](docs/stories/) — requirements and implementation stories.
- [docs/operations/](docs/operations/) — model runtime, benchmarking, and recovery guides.

The command-line entry point is `python -m job_automation`. Configuration examples need local paths and service settings; runtime data belongs in a configured directory outside the repository. See the component handoffs for setup and usage details.

The current checkout still needs reproducible packaging and wiring of the generation services into the CLI. Several handoffs also record pending live integration checks. The [improvement plan](docs/improvement-plan.md) assesses these gaps and proposes a staged evaluation of Hugging Face Transformers, LangChain, and LangGraph against the existing architecture.
