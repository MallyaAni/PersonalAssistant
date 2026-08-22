name: tasks/pick
used by: backend/tasks/picker.py -> pick_one (tasks and skills)
runs on: the routing model, a single forced tool call

A person asking to cancel "the weather one", pause "my Friday reminder",
or forget "the morning skill" is naming a saved item by meaning, not by
id. Matching those words to one of their tasks or skills is a judgement
about what they mean, so the model makes it, through a tool whose only
argument is the id of the item chosen - or no call at all when none of
them is what they described.

2026-08-22: added with scheduled tasks; generalized to skills the same day.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are given a short list of a person's saved items - scheduled tasks or
skills - each with an id, and the words they used to refer to one of them.
Call pick_item with the id of the item they mean. If their words match none
of the items, or could equally mean more than one, make no call.
