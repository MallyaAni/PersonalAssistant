name: referent/followup
used by: backend/services/followup.py -> resolve_followup (called by MainActionSelector before routing)
runs on: the routing model (schema-enforcing engine), one call per turn that has history
pinned by: functional/test_followup_resolution_behaviour.py

What the newest message is about, decided once, before anything acts on it.

Every incident of 2026-08-26/27 was a second turn about something the first
turn mentioned - "adjust this", "regenerate it", "does only one person win
at the end?", "which hat do you like better for this outfit?" - and each
component that had to know what "this" meant (the router, the search
composer, the task picker, the memory agent) worked it out separately and
could get it wrong its own way: a stretch reminder moved, a show searched as
another show. This step restates the message so it stands alone, names what
it refers to, and hands that one reading to all of them.

It restates; it never answers, adds facts, or changes the intent.

Pinned by backend/tests/functional/test_followup_resolution_behaviour.py.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are given the recent conversation and the newest message from the same person. Restate the newest message so that it stands on its own, for a reader who has not seen the conversation.

Replace every reference that leans on the conversation - "it", "this", "that", "they", "the one", "again", "at the end", "the villa", "this outfit" - with the exact thing the conversation names, copied as it is spelled there: the show, product, place, person, picture, reminder, or draft. Keep everything else as the person said it: their intent, their wording, their question. Never answer the message, never add a fact the conversation does not contain, and never replace the thing with a different one that seems similar. A question that only makes sense about the thing just discussed names it too, even with no pronoun in it: "based on what you know about us, what do you think we'd like?" right after talking about ice cream means "which ice cream flavours do you think we'd like?", and subject is "ice cream". If the message already stands on its own, return it unchanged.

Also say what the message refers to:
- picture: a picture the assistant made or was sent, including opinions and questions about it and requests to make it again;
- task: a reminder or scheduled task the person set up;
- scout: Scout's own sweep, check, digest, or its schedule;
- draft: text being written together - an email, a message, a plan - including changes to its tone or content;
- subject: a thing under discussion - a show, product, place, person, event;
- none: the message stands alone and refers to nothing earlier.

And the subject's name when there is one, spelled as the conversation spells it; empty otherwise.
