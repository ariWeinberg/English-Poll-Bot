from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

class QuestionGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedQuestion:
    question: str
    options: list[str]
    correct_option: str
    explanation: str


def _extract_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QuestionGenerationError(f"Gemini returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise QuestionGenerationError("Gemini JSON response must be an object")
    return data


def validate_question(data: dict[str, Any]) -> GeneratedQuestion:
    question = str(data.get("question", "")).strip()
    options_raw = data.get("options")
    correct_option = str(data.get("correct_option", "")).strip()
    explanation = str(data.get("explanation", "")).strip()

    if not question:
        raise QuestionGenerationError("Question is required")
    if len(question) > 255:
        raise QuestionGenerationError("Question is longer than GreenAPI's 255 character poll limit")
    if not isinstance(options_raw, list):
        raise QuestionGenerationError("Options must be a list")

    options = [str(option).strip() for option in options_raw if str(option).strip()]
    if len(options) < 2 or len(options) > 12:
        raise QuestionGenerationError("Poll must contain 2 to 12 options")
    if len(set(options)) != len(options):
        raise QuestionGenerationError("Poll options must be unique")
    if any(len(option) > 100 for option in options):
        raise QuestionGenerationError("Poll options must be 100 characters or fewer")
    if correct_option not in options:
        raise QuestionGenerationError("Correct option must exactly match one poll option")

    return GeneratedQuestion(
        question=question,
        options=options,
        correct_option=correct_option,
        explanation=explanation,
    )


class GeminiQuestionGenerator:
    def __init__(self, api_key: str, model: str = "gemini-3.5-flash") -> None:
        try:
            from google import genai
        except ModuleNotFoundError as exc:
            raise QuestionGenerationError(
                "google-genai is not installed. Run `pip install -e .` first."
            ) from exc
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate(self, source_text: str) -> GeneratedQuestion:
        prompt = f"""
Create one English multiple-choice comprehension question from the study text.
Return only JSON with keys: question, options, correct_option, explanation.
Rules:
- question must be <= 255 characters
- options must contain exactly 4 unique strings
- every option must be <= 100 characters
- correct_option must exactly equal one option
- avoid trick questions

Study text:
{source_text}
""".strip()
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        return validate_question(_extract_json(response.text or ""))
