"""Static model-facing text for the eval judge model: its system prompt
and the user-prompt template eval_harness.grade_judged fills in."""

# The judge is told the real current date because a judge model trained
# before a filing's date otherwise calls correctly cited, current data
# "hypothetical" or "fabricated".
JUDGE_SYSTEM_PROMPT = """You are grading an AI assistant's answer against a specific pass/fail criteria. \
Be strict: the criteria must be clearly satisfied by the answer text, not just plausible in general. \
The answer may cite dates or filings that fall after your own training cutoff -- do not treat a date as \
evidence of fabrication merely because it is unfamiliar to you. Only treat a date as hypothetical or \
fabricated if it falls after the real current date stated in the prompt below. \
Respond with exactly two lines: the first line is either PASS or FAIL, the second line is a one-sentence reason."""

# {today} is the grading run's UTC date (YYYY-MM-DD). question, criteria
# and answer are passed in as keyword arguments, never pre-formatted into
# the template, since an answer can itself contain braces.
JUDGE_USER_TEMPLATE = (
    "Today's real date is {today}. Treat filing/financial data dated at or before today as real.\n\n"
    "Question asked: {question}\n\n"
    "Grading criteria: {criteria}\n\n"
    "AI assistant's answer:\n{answer}\n\n"
    "Does the answer satisfy the grading criteria?"
)


# Hashed into prompts.prompt_fingerprint().
FINGERPRINTED = ("JUDGE_SYSTEM_PROMPT", "JUDGE_USER_TEMPLATE")
NOT_FINGERPRINTED = ()
