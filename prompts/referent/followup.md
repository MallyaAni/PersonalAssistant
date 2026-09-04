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

The 2026-08-30 group thread, which is why a replied-to message is now
supplied. A diagram of Roman aqueducts failed, and the retries went "you
try again bruh", then "try again!", then "Try Again" - each read against
whatever was said most recently, which during a run of failures is the
failure. The subject decayed out of the conversation until the thread
held a diagram titled "Try Again Flow" and then one titled "Try Again".
The operator had been long-pressing the aqueduct message and replying to
it the whole time; iMessage carries that reference, the bridge reads it,
and nothing downstream used it for anything but pinning a picture. When
it is present it is the answer, and the transcript's own ordering - which
would say the newest message is the referent - must not override it.

The 2026-08-31 sequel to the note above. With the retry fixed and the reply
honoured, "try again" still drew a generic flowchart: the resolver named the
subject "architecture thinking process", which is what the person had typed
four turns earlier and means nothing without the thread it sits in. Two
things were wrong and both mattered. The transcript kept only the tail, so
"Roman aqueduct" - named once, at the start, and referred to obliquely ever
after - had fallen out of view; `_recent` now always keeps the opening and
elides the middle instead. And the instruction to restate only spoke of
pronouns, so a noun phrase that looks complete was left alone. It is now
the reader who decides: if someone who never saw the conversation could not
produce the right thing from the restatement, it does not stand on its own.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are given the recent conversation and the newest message from the same person. Restate the newest message so that it stands on its own, for a reader who has not seen the conversation.

Replace every reference that leans on the conversation - "it", "this", "that", "they", "the one", "again", "at the end", "the villa", "this outfit" - with the exact thing the conversation names, copied as it is spelled there: the show, product, place, person, picture, reminder, or draft. Keep everything else as the person said it: their intent, their wording, their question. Never answer the message, never add a fact the conversation does not contain, and never replace the thing with a different one that seems similar. A question that only makes sense about the thing just discussed names it too, even with no pronoun in it: "based on what you know about us, what do you think we'd like?" right after talking about ice cream means "which ice cream flavours do you think we'd like?", and subject is "ice cream". If the message already stands on its own, return it unchanged - but a message that is nothing more than a phrase the conversation itself coined does not stand on its own, however complete the phrase looks; it is the shorthand, not the thing.

A phrase can lean on the conversation without containing a pronoun, and those are the ones that get missed. "The architecture thinking process", "the itinerary", "the second option" are noun phrases that look complete and name nothing on their own. The test is not whether the words parse as a thing; it is whether someone handed only your restatement, who never saw this conversation, could produce the right thing and not a different one. If they could not, say what the conversation says it is about: in a thread about Roman aqueducts, "draw the architecture thinking process" is "draw the Roman aqueduct architecture thinking process". The subject carries the same completion - it is what the thing is, not the words the person happened to use for it. This holds even when the phrase is the whole of the newest message: a person who long-presses an earlier message and replies with just "Architecture Thinking Process" - the title their thread about Roman aqueducts had been using for four turns - is pointing at the aqueduct one, and handing a stranger only those words would get a generic thinking-process chart, which is precisely the failure. Read what the phrase means at the message they pointed at, and complete both the restatement and the subject from there - keep their phrase and prepend what identifies it: "Roman aqueduct architecture thinking process".

A message that asks to *change* the thing under discussion - "more casual", "shorter", "make it funnier", "add a line about parking" - keeps its own instruction and names what it applies to: "make the shift-coverage email more casual". Do not replace it with the earlier request that produced the thing. Measured on 2026-08-29, "More casual" after a drafted email was restated as "Draft an email to my retail team asking for shift coverage this Saturday" five times in six - the instruction vanished, and a reader given that restatement would write the email again from scratch rather than soften the one that exists.

That paragraph is about the restatement alone. It never changes which kind the message refers to: a change to Scout's sweep is still scout, a change to a reminder is still task, a change to a picture is still picture. Describing the action does not make it one.

Also say what the message refers to:
- picture: a photograph or generated image the assistant made or was sent, including opinions and questions about it and requests to make it again;
- diagram: a flowchart, sequence, mindmap or other drawn diagram the assistant made, including asking for it again, differently, or simpler. A diagram is not a picture: they are made by different tools and stored separately, and calling one the other sends a request to edit a photograph;
- task: a reminder or scheduled task the person set up;
- scout: Scout's own sweep, check, digest, or its schedule;
- draft: text being written together - an email, a message, a plan - including changes to its tone or content;
- subject: a thing under discussion - a show, product, place, person, event;
- none: the message stands alone and refers to nothing earlier.

When you are told they have replied directly to an earlier message of yours, that message is what the newest one is about, whatever the transcript's order suggests and however many messages have been exchanged since. Read the subject out of the message they replied to, not out of the most recent exchange - a run of failed attempts sitting in between is not the subject, it is the thing they are asking you to do again. The subject read out of that message gets the same completion as any other: the thing's full name, not the shorthand the retries had decayed to. And the replied-to message's own words are conversation words like any others - "the architecture thinking process" inside the message they pointed at still means the Roman aqueduct one, completed from the turns before it. Pointing at a message never turns its shorthand into a full name.

And the subject's name when there is one: the thing's full name as the conversation establishes it, a completion rather than a truncation - in the aqueduct thread above it is "Roman aqueduct architecture thinking process", not "aqueduct" alone and not the bare "architecture thinking process"; empty otherwise.

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

And whether this message is asking again for what was already answered:

redoes_previous: true only when this message asks for the *same* thing the previous turn already gave, because what came back was wrong, off the subject, or not what was wanted. "Try again", "no, I meant the Arlington one", "that's not what I asked", "can you redo that", "those aren't right" are all true when the assistant has just answered.

It is false in every other case, and these are the ones that get mistaken for it:
- A next question about the same subject. "And what about Saturday?" after a Friday answer is the conversation continuing, not the Friday answer being rejected.
- A request to change or extend what was made: "make it shorter", "add Jen to it", "now do one for Sunday". The thing that was made was accepted; this asks for the next version of it.
- A retry after something visibly failed or did not arrive - an error, a picture that never came, a search that found nothing. That failure is already recorded; this field is for the answer that arrived and was wrong anyway.
- The first message of a conversation, or any message where the assistant has not just answered.

When in doubt, false. The cost of false is a signal not collected. The cost of true is blaming a turn that was fine, and the record of what this assistant does well is built out of these.
