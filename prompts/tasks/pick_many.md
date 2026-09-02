name: tasks/pick_many
used by: backend/tasks/picker.py -> pick_many (task sets)
runs on: the routing model, a single forced tool call
pinned by: functional/test_task_multi_selection_behaviour.py

A person asking to cancel "the paused ones", pause "the weather reminders"
or delete "all the morning ones" is naming a set of saved items by meaning,
not by id - and sometimes several at once. Matching those words to the
items is a judgement about what they mean, so the model makes it, through
a tool whose only argument is the ids of every item chosen - possibly
several, or none at all when none of them is what they described.

"one" and "a" name a single item; "all", "every", a plural like "the
weather ones", or a property like "the paused ones" may name several. Pick
every item the words cover, and no item the words do not cover.

2026-09-02: added with multi-task selection. "delete the paused ones" (a
real utterance) had reached a picker that returned exactly one id, so only
one task of a set could ever be cancelled.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are given a short list of a person's saved items - scheduled tasks or
skills - each with an id, and the words they used to refer to them. Call
pick_items with the ids of every item their words cover. Their words may
name one item ("the weather one") or several ("the paused ones", "all the
weather ones", "the morning reminders"). If their words match none of the
items, or name a property no item has, call pick_items with an empty list.
"This", "that", "it" and "the one" mean whatever the assistant said just
before, when that is given: if what the assistant just named is not one of
the items - a setting, an agent's own schedule such as Scout's sweep,
something not on the list - the answer is an empty list. Vague words never
earn the closest item; a wrong pick changes something the person did not
mention.
