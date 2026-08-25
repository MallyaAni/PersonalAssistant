"""The word a scheduled check says when it has nothing to say.

A conditional task - "message me if search credits are low", "tell me when
the price drops under 40" - fires on its schedule whether or not the
condition holds. The reply model answers with this token alone when it does
not, and the runner sends nothing. It is a single fixed token rather than a
judgement about the prose so a real message can never be mistaken for
silence.
"""

NOTHING_TO_REPORT = "NOTHING_TO_REPORT"


# Whether a reply is the silence token and nothing else, allowing for the
# punctuation and quoting a model adds around a word it was told to write.
def is_nothing_to_report(reply: str) -> bool:
    return reply.strip().strip("\"'`*_.!").strip() == NOTHING_TO_REPORT
