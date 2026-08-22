name: tasks/pick
used by: backend/tasks/picker.py -> pick_task
runs on: the routing model, a single forced tool call

A person asking to cancel "the weather one" or pause "my Friday reminder"
is naming a task by meaning, not by id. Matching those words to a saved
task is a judgement about what they mean, so the model makes it, through a
tool whose only argument is the id of the task chosen - or no call at all
when none of them is what they described.

2026-08-22: added with the scheduled-tasks feature (docs/TASKS_ARCHITECTURE.md).

===== PROMPT BELOW — everything under this line is sent to the model =====

You are given a person's scheduled tasks, each with an id, and the words
they used to refer to one of them. Call pick_task with the id of the task
they mean. If their words match none of the tasks, or could equally mean
more than one, make no call.
