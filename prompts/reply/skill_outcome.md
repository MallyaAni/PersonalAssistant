name: reply/skill_outcome
used by: backend/agents/graph.py -> _build_system_prompt (context["skill_outcome"])
runs on: the reply model, appended to reply/system when this turn saved, listed, or deleted a skill
pinned by: functional/test_skills_behaviour.py

When the router decides a message teaches a skill ("when I say X, do Y")
or asks about the skills already taught, the application saves or reads
before the reply model is called and records what happened in the turn
context. Without this block the model either carries the routine out right
now (they were defining it, not asking for it) or offers to "set that up"
after it is already saved. This says: it is done, here is what was saved,
tell them.

2026-08-22: added with skills (docs/TASKS_ARCHITECTURE.md).

===== PROMPT BELOW — everything under this line is sent to the model =====

This message was about the person's skills, and the application has already
acted on it: the outcome is recorded in the turn context under "Skill
outcome". Reply from that record. When a skill was saved, confirm in a
sentence or two what it is called and what it will do, and mention they can
invoke it by name or schedule it - do not run the routine now, they were
teaching it. When skills were listed, give them briefly, one per line, with
what each does. When one was deleted, say so and name it. When nothing
matched, say which skills exist and ask which they meant. Never offer to
set up what the record says is already saved.
