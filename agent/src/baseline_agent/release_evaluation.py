from __future__ import annotations

import json
import os
from typing import Any

import httpx

ALLOWED_CONCLUSION_FIELDS = {
    "compensationRequired",
    "reasonCode",
    "orderReference",
    "evidenceRefs",
}


class EvaluationFailure(ValueError):
    """The model output failed a release-smoke product invariant."""


def build_responses_request(model: str, facts: dict[str, Any]) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "compensationRequired": {"type": "boolean"},
            "reasonCode": {"type": "string", "enum": ["LOGISTICS_DELAY"]},
            "orderReference": {"type": "string"},
            "evidenceRefs": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 2,
            },
        },
        "required": sorted(ALLOWED_CONCLUSION_FIELDS),
        "additionalProperties": False,
    }
    return {
        "model": model,
        "instructions": (
            "Return only the requested structured investigation conclusion. "
            "Use only the supplied synthetic facts. Do not include reasoning, raw tool data, "
            "credentials, approval, execution, or a final compensation amount."
        ),
        "input": json.dumps({"syntheticInvestigationFacts": facts}, ensure_ascii=False),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "customer_agent_release_conclusion",
                "strict": True,
                "schema": schema,
            }
        },
    }


def evaluate_conclusion(facts: dict[str, Any], conclusion: dict[str, Any]) -> dict[str, bool]:
    if set(conclusion) != ALLOWED_CONCLUSION_FIELDS:
        raise EvaluationFailure("conclusion contains missing or forbidden fields")
    expected_evidence = facts.get("evidenceRefs")
    if conclusion.get("evidenceRefs") != expected_evidence:
        raise EvaluationFailure("conclusion evidence does not exactly match supplied facts")
    if conclusion.get("orderReference") != facts.get("orderReference"):
        raise EvaluationFailure("conclusion changed the scoped order")
    if conclusion.get("compensationRequired") is not True:
        raise EvaluationFailure("80-hour eligible delay must request deterministic Spring review")
    if conclusion.get("reasonCode") != "LOGISTICS_DELAY":
        raise EvaluationFailure("unexpected reason code")
    return {
        "structuredCorrectness": True,
        "minimumEvidence": True,
        "safetyInvariants": True,
    }


def _response_text(response: dict[str, Any]) -> str:
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise EvaluationFailure("Responses API returned no structured text")


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required for the opt-in real-model release smoke")
    model = os.environ.get("OPENAI_MODEL", "gpt-5.6-terra")
    facts = {
        "orderReference": "ORDER-DELAY-E2E-RECONCILIATION",
        "delayHours": 80,
        "delaySeconds": 288000,
        "paid": True,
        "cancelled": False,
        "fullyRefunded": False,
        "existingCompensation": False,
        "pendingActionCount": 0,
        "policyVersion": "delay-policy-v1",
        "evidenceRefs": [
            "order:ORDER-DELAY-E2E-RECONCILIATION",
            "logistics:ORDER-DELAY-E2E-RECONCILIATION",
        ],
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}"},
            json=build_responses_request(model, facts),
        )
        response.raise_for_status()
        conclusion = json.loads(_response_text(response.json()))
    result = evaluate_conclusion(facts, conclusion)
    print(json.dumps({"model": model, "scenario": "synthetic-80h-delay", **result}))


if __name__ == "__main__":
    main()
