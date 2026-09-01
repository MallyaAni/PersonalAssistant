name: memory/digest
used by: backend/memory/digest.py -> summarise()
runs on: the reply model (MAIN_LLM_MODEL), via get_reasoning_llm_client()
pinned by: functional/test_conversation_digest_behaviour.py
placeholders: {previous} {exchanges} {max_words}

Compresses a stretch of conversation into a digest that later turns read as
background. It runs once every MEMORY_SUMMARY_INTERVAL turns, after the reply
has already been sent, so it never delays an answer.

Why the main model and not the small one. This is prose compression, which is
the reasoning model's job, and it is not schema-bound so it avoids the engine
defect that pins six other callers to the 4B. More importantly a bad summary is
worse than no summary: truncation drops material honestly, while a weak model
invents a tidy narrative, and that invention then enters every later prompt as
though the user had said it.

The single most important instruction here is that it must not add anything. A
digest is read later as a record of what happened, so a plausible detail
introduced at this step becomes indistinguishable from something the user
actually told us. That is why the prompt spends more words forbidding invention
than describing style.

The failure this is meant to replace was not a bad summary but no summary at
all: the previous implementation concatenated verbatim exchanges onto the
previous digest forever, so it only grew. If this call fails the caller falls
back to bounded truncation, which is worse than a good digest and much better
than an unbounded one.

The artifact line exists because a long working thread - most visibly a coding
one - can outlive the ten-turn window, and the durable fact later turns depend
on is which file or document was in play and what was decided about it, not the
chatter around it. "What the person is trying to do" already carries much of
this; naming the artifact explicitly keeps it when the task is described once
and then worked on across many later turns that never restate it.

Do not ask for headings, bullets, or a structure. Later turns read this as
background prose, and imposed structure makes a model treat it as a document to
be discussed rather than as context it already knows.

===== PROMPT BELOW — everything under this line is sent to the model =====
You are compressing part of a conversation into notes that you yourself will
read later, as background, in the same conversation.

Write at most {max_words} words of plain prose. No headings, no bullet points,
no preamble, no closing remark. Write only the notes.

Keep, in rough order of importance:
- what the person is trying to do, and any constraint they stated
- the artifact they are working on, when they named one - a file, a piece of
  code, a document, a diagram, an item - and what was decided or changed
  about it, by name
- decisions reached, and anything explicitly ruled out
- facts they gave about themselves or their situation
- questions left open

Leave out pleasantries, your own phrasing, and anything already obvious from
the words themselves.

Do not add anything. Every statement in your notes must be traceable to the
material below. If something was implied but never said, leave it out. If two
statements conflict, say that they conflict rather than choosing between them.
Never guess at a name, a number, a date, or a preference that was not stated.
Write about the person in the third person.

{previous}Conversation to compress:
{exchanges}
