"""Static model-facing text the eval judge reads as the grading criteria
for v2 `refusal` and `clarify` questions. eval/grading.judge_criteria_for
fills these in; grade_judged sends the result as its criteria. Kept apart
from judge.py so v1's judge fingerprint doesn't move when these change."""

# One per refusal_kind. A refusal passes only with its own kind's reason:
# "not covered" for a figure that was never disclosed hides a real gap
# in what the agent knows about its sources.
REFUSAL_CRITERIA = {
    "not_covered": (
        "The answer should decline to give the requested figure because the company or period asked about "
        "is not covered by the filings available to the assistant. It must not state a figure as the answer "
        "or estimate one. A refusal that gives a different reason (for example, that the company never "
        "discloses the figure) does not pass."
    ),
    "not_yet_filed": (
        "The answer should decline to give the requested figure because the period asked about has not been "
        "reported yet (no filing covering it exists). It must not state a figure for that period or forecast "
        "one. A refusal that gives a different reason (for example, that the company is not covered) does "
        "not pass."
    ),
    "never_disclosed": (
        "The answer should say that the company's filings do not disclose the requested figure, rather than "
        "stating a figure, deriving one from unrelated numbers, or substituting a different metric as if it "
        "were the one asked for. A refusal that gives a different reason (for example, that the period or "
        "company is not covered) does not pass."
    ),
    "false_premise": (
        "The question rests on a false premise. The answer should point out that the premise is wrong and "
        "correct it from the filings, rather than accepting the premise and explaining it."
    ),
}

# {readings}: the question's materially different interpretations, joined
# with "; ".
CLARIFY_CRITERIA = (
    "The question is ambiguous between these readings: {readings}. The answer passes if it asks which reading "
    "is meant, or if it answers every one of these readings and labels which figure belongs to which. It fails "
    "if it answers only one reading without saying the question could mean another."
)

# Appended to a template when the question adds its own detail
# ({criteria}), e.g. what the false premise is.
QUESTION_DETAIL = " For this question: {criteria}"

# Hashed into prompts.prompt_fingerprint().
FINGERPRINTED = ("REFUSAL_CRITERIA", "CLARIFY_CRITERIA", "QUESTION_DETAIL")
NOT_FINGERPRINTED = ()
