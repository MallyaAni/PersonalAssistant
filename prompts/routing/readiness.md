name: routing/readiness
used by: backend/services/readiness.py -> judge_readiness (called by the iMessage worker through /chat/readiness)
runs on: the routing model (schema-enforcing engine), temperature 0
pinned by: functional/test_burst_readiness_behaviour.py

Texting arrives in fragments - "ok" / "thai then" / "friday?" - and a reply
to each one answers a thought that is not finished. A timer cannot tell a
pause from an ending, so the decision is made by meaning: is the person
done, and does what they said want an answer. Added 2026-08-28 with group
chats, where the same judgement also keeps the assistant from answering a
room's every "sounds good". Positive tapbacks add a third judgement: whether
the exact bubble they target offered an action that "yes" unambiguously accepts.

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

Live, later the same day: "we are a groupie!!" sent as a reply to the
assistant's bubble was judged as wanting no reply, and the room got
silence for a deliberate address. Adding a rule for that here cost three
other cases their verdicts (25 -> 21), so the rule lives in code instead:
the worker answers a reply to its bubble or a mention regardless of
needs_reply and asks this judgement only whether the message is finished.
The judgement is still told how the message reached the assistant.

First live group turn (2026-08-28): a tap-and-hold reply "what location
are you looking?" was judged unfinished, so the answer waited out the whole
safety cap. The rule that a question mark ends a thought was added, the
case pinned, and the cap lowered from 90 s to 45 s.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are reading a text conversation and deciding three things about what the person has sent since the assistant's previous message. Read the fragments together as one thought in progress.

complete: true when the person has finished saying what they mean - the fragments, read together in order, form a whole statement, question, or answer. Judge the end of the last fragment, not the earlier ones: a lead-in ("ok so", "quick question", "two things") is completed by whatever follows it, so "ok so" followed by "can you find a thai place near dupont" is complete. false only when the thought is still open at the end of the last fragment: it ends mid-thought ("ok so", "what about", "and also"), it announces more that has not arrived yet, or it is a first word that clearly wants a continuation. Ordinary short messages are complete: "thai then", "friday?", "yes", "no thanks" are each finished thoughts. A fragment that ends with a question mark is a finished question, however it is worded ("what location are you looking?" is complete), and texting shorthand is finished too ("where r u", "u coming?").

needs_reply: true when what they sent asks something, requests something, answers a question the assistant asked, decides something the assistant offered to act on, or otherwise expects the assistant to respond. false only when the fragments are a closing acknowledgement that expects nothing back - "ok", "thanks!", "sounds good", "great, see you then", "👍" - with no question, request, or decision inside them. A message that thanks and then asks is true. A bare emoji or reaction alone normally needs no reply. In a group chat, a message that names another person as the one to answer it ("Jen, are you bringing Sam?") is that person's to answer, not the assistant's: needs_reply is false even though it is a complete question; a message that names nobody, or names the assistant, is for the assistant.

accepts_offer: false for every ordinary text or reaction. It can be true only when the setting explicitly says this is a positive tapback on the exact assistant message shown. Then it means "yes, do that" when that message offered to perform a concrete action or asked for yes-or-no confirmation before acting, and only when "yes" answers it unambiguously. An offer stated as "I can do X if you want" is still an offer: when the only missing condition is the person's assent, the positive tapback supplies it. A choice, an open question, or a request for missing details is not accepted because "yes" does not supply the missing answer. A message that merely answered, stated a fact, joked, or expressed warmth offered nothing to accept. Whether such an ambiguous tapback might deserve a conversational clarification is irrelevant to accepts_offer: return false, because no action was authorized.

reason: at most one short sentence.
