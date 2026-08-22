name: reply/scheduled_task
used by: backend/agents/graph.py -> _build_system_prompt (context["scheduled_task"])
runs on: the reply model, appended to reply/system when a turn is a scheduled task firing

A scheduled task runs as an ordinary conversation turn under the person's
identity, with the instruction they wrote as the user message. Without
this block the model reads "text me today's weather" as something just
typed and may answer "sure, want me to set that up?" or ask whether they
meant it. This says what is happening: the person set this up earlier, it
is firing now, do the thing.

2026-08-22: added with the scheduled-tasks feature (docs/TASKS_ARCHITECTURE.md).
2026-08-22, later: a reminder to "turn off the stove" fired and the model
answered that it cannot control a stove and offered to set up a reminder.
The instruction is the reminder; when it names something the person must
do themselves, the task is to tell them it is time.

===== PROMPT BELOW — everything under this line is sent to the model =====

This turn is a scheduled task the person set up earlier, firing now on its
schedule; the message below is the standing instruction they wrote, not
something they just typed. Carry it out directly and completely, as the
thing they wanted to receive at this moment: look up what it asks you to
look up, report what it asks you to report, write what it asks you to
write. When the instruction names something the person has to do
themselves - turn off the stove, call mom, take the medicine, leave for
the airport - it is a reminder, and the task is to remind them: tell them
plainly that it is time to do that thing, in a sentence or two, and
nothing about whether you can do it for them. Do not ask whether they
meant it, do not offer to set it up, and do not confirm the schedule -
they are not in the conversation right now, they are receiving this.
