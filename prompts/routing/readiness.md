name: routing/readiness
used by: backend/services/readiness.py -> judge_readiness (called by the iMessage worker through /chat/readiness)
runs on: the routing model (schema-enforcing engine), temperature 0
pinned by: functional/test_burst_readiness_behaviour.py

Texting arrives in fragments - "ok" / "thai then" / "friday?" - and a reply
to each one answers a thought that is not finished. A timer cannot tell a
pause from an ending, so the decision is made by meaning: is the person
done, and does what they said want an answer. Added 2026-08-28 with group
chats, where the same judgement also keeps the assistant from answering a
room's every "sounds good".

The two failure modes to hold in balance: replying too early (answering
"ok so" before the question lands) and staying quiet when an answer was
wanted (treating "thai?" as chatter). When in doubt about whether a reply
is wanted, say it is; when in doubt about whether the person is finished,
say they are not - the safety cap in the worker answers a long silence.

First run on the real routing model (2026-08-28): 15/17. "ok so" + "can you
find a thai place near dupont" was judged unfinished because the first
fragment announced more - the rule now says to judge the end of the last
fragment. "no thanks" to "Want me to book it for 7?" was judged as wanting
no reply; that reading is accepted (nothing was booked, silence is the
honest state) and the case is left unpinned either way.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are reading a text conversation and deciding two things about what the person has sent since the assistant's previous message. Read the fragments together as one thought in progress.

complete: true when the person has finished saying what they mean - the fragments, read together in order, form a whole statement, question, or answer. Judge the end of the last fragment, not the earlier ones: a lead-in ("ok so", "quick question", "two things") is completed by whatever follows it, so "ok so" followed by "can you find a thai place near dupont" is complete. false only when the thought is still open at the end of the last fragment: it ends mid-thought ("ok so", "what about", "and also"), it announces more that has not arrived yet, or it is a first word that clearly wants a continuation. Ordinary short messages are complete: "thai then", "friday?", "yes", "no thanks" are each finished thoughts.

needs_reply: true when what they sent asks something, requests something, answers a question the assistant asked, decides something the assistant offered to act on, or otherwise expects the assistant to respond. false only when the fragments are a closing acknowledgement that expects nothing back - "ok", "thanks!", "sounds good", "great, see you then", "👍" - with no question, request, or decision inside them. A message that thanks and then asks is true. A bare emoji or reaction alone is false. In a group chat, a member's remark that is clearly to another member and not to the assistant is false.

reason: at most one short sentence.
