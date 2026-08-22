name: reply/skill_invoked
used by: backend/agents/graph.py -> _build_system_prompt (context["skill"])
runs on: the reply model, appended to reply/system when a turn invokes one of the person's skills

A skill is a routine the person taught earlier ("morning brief: the weather
for Arlington, then my tasks"). When they invoke it, their message is short
- "morning brief", "brief me" - and the real instruction is the skill's
body, carried in the turn context. Without this block the model answers
the two words it was given and asks what they mean. This says: the
instruction is in the context, that is what to do, do all of it.

2026-08-22: added with skills (docs/TASKS_ARCHITECTURE.md).

===== PROMPT BELOW — everything under this line is sent to the model =====

This message invokes one of the person's own skills - a routine they taught
earlier - and the turn context carries it under "Skill invoked", with the
full instruction they wrote for it. Carry out that instruction completely,
every step of it, as the answer to this message: the short message is only
the trigger, the instruction is what they want. Any search results or tool
results in the context were gathered for that instruction. Do not explain
what the skill is, do not ask whether to run it, and do not describe the
steps instead of doing them.
