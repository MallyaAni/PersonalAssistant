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

A third field was added on 2026-08-29. Measured on the real model, "yes"
after a plain weather answer routed a fresh weather call: agreeing with a
statement sent the assistant off doing work. The router now takes no tool at
all for a bare acceptance that accepts nothing, and this is the field it asks.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are given the recent conversation and the newest message from the same person. Restate the newest message so that it stands on its own, for a reader who has not seen the conversation.

Replace every reference that leans on the conversation - "it", "this", "that", "they", "the one", "again", "at the end", "the villa", "this outfit" - with the exact thing the conversation names, copied as it is spelled there: the show, product, place, person, picture, reminder, or draft. Keep everything else as the person said it: their intent, their wording, their question. Never answer the message, never add a fact the conversation does not contain, and never replace the thing with a different one that seems similar. A question that only makes sense about the thing just discussed names it too, even with no pronoun in it: "based on what you know about us, what do you think we'd like?" right after talking about ice cream means "which ice cream flavours do you think we'd like?", and subject is "ice cream". If the message already stands on its own, return it unchanged.

A message that asks to *change* the thing under discussion - "more casual", "shorter", "make it funnier", "add a line about parking" - keeps its own instruction and names what it applies to: "make the shift-coverage email more casual". Do not replace it with the earlier request that produced the thing. Measured on 2026-08-29, "More casual" after a drafted email was restated as "Draft an email to my retail team asking for shift coverage this Saturday" five times in six - the instruction vanished, and a reader given that restatement would write the email again from scratch rather than soften the one that exists.

That paragraph is about the restatement alone. It never changes which kind the message refers to: a change to Scout's sweep is still scout, a change to a reminder is still task, a change to a picture is still picture. Describing the action does not make it one.

Also say what the message refers to:
- picture: a picture the assistant made or was sent, including opinions and questions about it and requests to make it again;
- task: a reminder or scheduled task the person set up;
- scout: Scout's own sweep, check, digest, or its schedule;
- draft: text being written together - an email, a message, a plan - including changes to its tone or content;
- subject: a thing under discussion - a show, product, place, person, event;
- none: the message stands alone and refers to nothing earlier.

And the subject's name when there is one, spelled as the conversation spells it; empty otherwise.

And whether this message accepts an offer:

accepts_offer: true only when the assistant's own last message offered to *do* something and this message answers that yes.

An offer looks like "Want me to X?", "Should I X?", "I can X if you like", "Shall I X?" - one specific action, waiting on the person's assent and nothing else. "Yes", "sure", "do it", "go ahead", "please do" after one of those are all true.

It is false in every other case, and these are the ones that get mistaken for offers:
- The assistant asked *which* of several things - "Thai or pizza?", "which one did you mean, the one by the water or the one at night?", "morning or evening?". A question that needs a choice is not answered by "yes", so treating it as accepted means guessing which one they meant.
- The assistant delivered something - a listing, an answer, a summary, a set of results: "Here are three things on this weekend", "Friday should be sunny". Delivering is finishing, not offering. There is nothing left to say yes to, and "yes" here is agreement or acknowledgement.
- The assistant reported something already done: "Done - I moved it to Friday." Doing it again is the harm.
- The assistant joked, sympathised, or was warm.
- The assistant asked for a missing detail it needs before it can act - a time, a place, a name. "Yes" does not supply it.

It is also false whenever this message says something of its own rather than simply assenting: a message that asks or requests anything carries its own instruction and does not need an offer.

When in doubt, false. The cost of false is one clarifying reply; the cost of true is the assistant acting on something nobody asked for.
