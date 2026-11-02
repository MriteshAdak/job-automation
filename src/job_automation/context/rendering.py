"""Prompt rendering boundary for CONTEXT-01 whole-prompt budgeting."""

from __future__ import annotations

import json

from job_automation.context.ports import PromptRendererPort
from job_automation.context.records import JsonContextRequest, RenderedPrompt


class DefaultPromptRenderer(PromptRendererPort):
    """Renders instructions, schema instructions, job data, and candidate JSON into a whole prompt."""

    def __init__(self, template_version: str = "v1") -> None:
        self.template_version = template_version

    def render(
        self,
        request: JsonContextRequest,
        candidate_json: str,
    ) -> RenderedPrompt:
        """Render complete structured prompt and capture individual component substrings.

        Guarantees that job posting text and candidate JSON are treated strictly as data.
        """
        if request.chat_template_version == "gen03-json-v1":
            # JSON quoting prevents data from closing a block or creating a new header.
            def block(label, value):
                data = json.dumps(value, ensure_ascii=True, sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e")
                return f"\n{label}_JSON_DATA\n{data}\n"
            instructions = request.instruction_text.strip() + "\n"
            schema = (request.output_schema_text or "").strip() + "\n"
            job = block("JOB", request.job_content.model_dump(mode="json"))
            requirements = block("REQUIREMENTS", request.requirements)
            candidate = block("CANDIDATE", json.loads(candidate_json))
            return RenderedPrompt(
                full_prompt=instructions + schema + job + requirements + candidate,
                instruction_text=instructions, output_schema_text=schema, job_text=job,
                requirements_text=requirements, candidate_json=candidate,
                framing_text="JOB_JSON_DATA REQUIREMENTS_JSON_DATA CANDIDATE_JSON_DATA",
                render_template_version="gen03-json-v1",
            )
        framing_parts: list[str] = []

        # 1. Instructions
        instruction_str = request.instruction_text.strip()
        rendered_instructions = ""
        if instruction_str:
            rendered_instructions = f"### System Instructions\n{instruction_str}\n\n"
            framing_parts.append("### System Instructions\n\n\n")

        # 2. Output Schema
        output_schema_str = (request.output_schema_text or "").strip()
        rendered_output_schema = ""
        if output_schema_str:
            rendered_output_schema = f"### Expected Output Format\n{output_schema_str}\n\n"
            framing_parts.append("### Expected Output Format\n\n\n")

        # 3. Job Posting
        job = request.job_content
        job_lines = [
            f"Title: {job.title}",
            f"Company: {job.company_name_hint}",
            f"Workplace: {job.workplace_type.value}",
        ]
        if job.locations:
            loc_str = ", ".join(loc.raw_text for loc in job.locations)
            job_lines.append(f"Locations: {loc_str}")
        job_lines.append(f"Description:\n{job.description_clean}")
        job_body = "\n".join(job_lines)
        rendered_job = f"### Target Job Posting\n{job_body}\n\n"
        framing_parts.append("### Target Job Posting\n\n\n")

        # 4. Requirements
        rendered_reqs = ""
        if request.requirements:
            req_items = "\n".join(f"- {req}" for req in request.requirements)
            rendered_reqs = f"### Job Requirements\n{req_items}\n\n"
            framing_parts.append("### Job Requirements\n\n\n")

        # 5. Candidate Profile Evidence
        rendered_candidate = f"### Candidate Profile Evidence\n{candidate_json}\n"
        framing_parts.append("### Candidate Profile Evidence\n\n")

        full_prompt = (
            f"{rendered_instructions}"
            f"{rendered_output_schema}"
            f"{rendered_job}"
            f"{rendered_reqs}"
            f"{rendered_candidate}"
        )

        framing_text = "".join(framing_parts)

        return RenderedPrompt(
            full_prompt=full_prompt,
            instruction_text=rendered_instructions,
            job_text=rendered_job,
            requirements_text=rendered_reqs,
            output_schema_text=rendered_output_schema,
            candidate_json=rendered_candidate,
            framing_text=framing_text,
            render_template_version=self.template_version,
        )

