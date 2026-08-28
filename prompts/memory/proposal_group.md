name: memory/proposal_group
used by: backend/memory/proposal_agent.py -> propose (group turns only), appended to memory/proposal with the roster
runs on: the routing model (schema-enforcing engine)
pinned by: functional/test_group_attribution_behaviour.py

In a group chat the fact "we're going to Thai on Friday" is the group's;
"I love hiking" is the speaker's; "Jen hates cilantro", said by Ani, is
about Jen but on Ani's word. The agent says who each fact is about with
names from the roster, and the application decides whose memory it lands
in (backend/memory/attribution.py) - never another member's on someone
else's say-so. No regex: "Jen and I", "us", "the two of us" are read for
meaning. Added 2026-08-28. The deploy that carried it (#9) found its first
gap the same day: "Scout, just so you know, we all settled on thai for
friday dinner" produced no proposal at all - the agent read the group's
decision as nobody's fact - while "Jen and I are doing Thai on Friday at 7"
captured. The sentence saying a decision made together is the group's own
fact was added and the sweep journey re-run.

===== PROMPT BELOW — everything under this line is sent to the model =====

This message was sent in a group chat by {speaker}. The people in the chat are: {roster}. The rules above still hold, with one change: a fact may be about the speaker, about the whole group, or about another named member, and you must say who with the about field - a list of names exactly as given in the roster, or "the group" when it is about everyone in the chat or about the group's plans together. "I" and "me" are {speaker}. "We", "us", "both of us", "the two of us", "Jen and I" name the speaker together with others: use "the group" when that covers everyone in the chat, otherwise list each person named. What the chat has decided, planned, or arranged together is the group's own stable fact, exactly as a first-person fact is the speaker's in a one-to-one message: "we're doing Thai on Friday", "we all settled on thai for friday dinner", "let's meet at 7" each fill semantic_fact with about ["the group"]. A member telling you the group's decision so that you know it ("just so you know", "for the record") is stating that fact, not asking a question. What another person likes, does, or is may now be captured when a member states it plainly, with that person's name in about; it is still never captured as the speaker's own preference. Leave about empty only when nothing at all is captured.
