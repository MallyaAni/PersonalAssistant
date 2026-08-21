"""Canonical visual observation prompt owned by the vision agent."""

from backend.core.prompts import load

CANONICAL_OBSERVATION_PROMPT = load("vision/observe").strip()

# The browser sends this exact neutral question when an attachment has no text.
DEFAULT_UPLOAD_QUESTION = "Describe this image, including any text you can read."


VISUAL_QUESTION_PROMPT = load("vision/question").strip()


# Put every image question behind the same evidence and uncertainty contract.
def build_visual_question_prompt(question: str) -> str:
    return f"{VISUAL_QUESTION_PROMPT}\n\nUser question:\n{question.strip()}"
