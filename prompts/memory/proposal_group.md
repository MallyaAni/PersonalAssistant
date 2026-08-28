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
meaning. Added 2026-08-28.

===== PROMPT BELOW — everything under this line is sent to the model =====

This message was sent in a group chat by {speaker}. The people in the chat are: {roster}. The rules above still hold, with one change: a fact may be about the speaker, about the whole group, or about another named member, and you must say who with the about field - a list of names exactly as given in the roster, or "the group" when it is about everyone in the chat or about the group's plans together. "I" and "me" are {speaker}. "We", "us", "both of us", "the two of us", "Jen and I" name the speaker together with others: use "the group" when that covers everyone in the chat, otherwise list each person named. A plan, decision, or arrangement the chat has made ("we're doing Thai on Friday", "let's meet at 7") is a semantic_fact about the group. What another person likes, does, or is may now be captured when a member states it plainly, with that person's name in about; it is still never captured as the speaker's own preference. Leave about empty only when nothing at all is captured.
