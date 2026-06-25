import pytest

from app.question_generator import QuestionGenerationError, validate_question


def test_validate_question_accepts_greenapi_safe_question():
    question = validate_question(
        {
            "question": "What is the main idea?",
            "options": ["A", "B", "C", "D"],
            "correct_option": "A",
            "explanation": "A is stated in the text.",
        }
    )

    assert question.correct_option == "A"
    assert len(question.options) == 4


def test_validate_question_rejects_duplicate_options():
    with pytest.raises(QuestionGenerationError):
        validate_question(
            {
                "question": "What is the main idea?",
                "options": ["A", "A", "C", "D"],
                "correct_option": "A",
            }
        )


def test_validate_question_rejects_correct_answer_not_in_options():
    with pytest.raises(QuestionGenerationError):
        validate_question(
            {
                "question": "What is the main idea?",
                "options": ["A", "B", "C", "D"],
                "correct_option": "E",
            }
        )
