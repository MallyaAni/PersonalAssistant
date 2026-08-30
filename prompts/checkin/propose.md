name: checkin/propose
used by: backend/core/checkin.py
runs on: the routing model (schema-enforcing engine)
pinned by: functional/test_check_in_proposal_behaviour.py

What this is for, in the operator's words on 2026-08-30: "it would be nice
to have the agent check in on something if it knows for example how was the
visit to national harbor? (this is easier since it knows the time of the
event) or if the user isnt feeling well like an occasional check in on how
they're doing".

An outing and an illness were the examples, not the specification. The
operator's next instruction was to "account for scenarios we haven't seen
before", and the failure that instruction is against is a prompt that
enumerates situations: a list of categories silently caps what can ever be
noticed at whatever someone thought of first, and "waiting to hear back
about the flat" or "nervous about Thursday's exam" fall outside it while
being exactly the same shape. So the rule below is stated as a shape - a
thing with an outcome, arriving at a knowable time, that a person would be
glad to be asked about - and the two examples appear only as illustrations
of it.

For the same reason the model writes the question rather than choosing a
template, and says which of two governing kinds it is rather than which of
several situations. `wellbeing` is separate only because it alone is
rationed and alone must never be asked in a room.

`calls_off` exists because the worst thing this feature can do is not
silence. It is asking how a trip went that the person already said was
cancelled. The same call that notices a plan notices the plan being called
off or moved, because it is the only thing that can tell that "we bailed on
the Harbor thing" is about the outing already waiting. The caller only acts
on a subject copied back exactly from the list it supplied, so a paraphrase
takes nothing down.

The failure this prompt is written against is not missing a check-in. It is
arming one every turn. This call sees a single message with what is already
waiting, and nothing else, so a prompt that leans towards yes produces a
thread that asks after everything the person ever mentioned. Reluctance is
the default.

The caller enforces every limit that keeps this civil - how many may be
armed, how close together, how far ahead, which hour - in code, so this
prompt never has to be trusted with them. It only decides whether the thing
is worth coming back to at all, what to ask, and roughly when.

What the shape of this call cost to find, measured 2026-08-30, three runs
per case. Two of the three fixes were the field order, not the wording, and
each was found by a failure that looked like a wording problem.

With `check_in` declared first it is decided before anything justifying it
exists: "I've got a dentist appointment tomorrow morning" came back false
beside a perfectly good subject, question, day and hour - 0/3, the model
having worked out exactly what to ask and then said no.

Moving it last broke a worse thing. Every judgement then passed through a
kind, a subject, a question, a day and an hour before it could say "nothing
here", and for the nine messages in ten that are nothing, all of that is
invented under constraint. Every `following_up` case went false and every
`wellbeing` case went true: a coupling to the invented fields, not a reading
of the message.

What works is a line of reading first, then the decision. The reading has to
name every shape the call handles or the shape it omits disappears: framed
only as "a thing that will have turned out by a date", wellbeing went 0/3,
because an illness is not that. Adding news about something already waiting
to the same line, and moving `calls_off` up beside it, brought
cancellations back from 0/3 to 3/3 - they had collapsed the moment the
reading existed, because the reading said "nothing", the decision agreed,
and by the time `calls_off` was reached the message was already settled as
being about nothing.

The last of the three was arithmetic rather than order. Asked from a
Thursday, "we're heading to National Harbor on Saturday evening" answered
after_days 2 - Saturday morning, asking how an evening went before the
evening. Saying that Saturday is two days away is easy; remembering to add
one to it every time is not, so the call now says when the thing happens
and the caller adds the day. The check-in can no longer land before the
thing it asks about, and where that makes it a day later than strictly
needed, that is the trade taken deliberately.

Where it stands: eleven things worth noticing at 3/3 each, including five
shapes no template was written for, and every one of them asked about after
it is over - Saturday evening asked on Sunday, a Friday trip on Tuesday, a
Monday first day on Tuesday. Twelve ordinary turns at 0/36, including "a
bit tired this morning but I'm fine" and a brother's operation. Plans
beyond six weeks refused rather than pulled closer. Three wordings of the
same waiting outing armed nothing. Three of four cancellation phrasings at
3/3, with "we bailed on Saturday, staying in instead" - which never names
the outing - at 0/3. A plan that moved is recognised 3/3 and dropped, but
the new date is not armed in the same breath; the row is removed rather
than disabled precisely so that mentioning it again arms it afresh.

===== PROMPT BELOW — everything under this line is sent to the model =====

First write one line of reading: what, if anything, in this message is either a thing of theirs that will have turned out one way or another by a date you can work out, or something they have said about how they themselves are doing, or news about one of the things already waiting. If it is none of those, write "nothing".

Then, before deciding anything else, fill in calls_off from that reading. Then decide, and answer false whenever the reading is "nothing" - which it is for most messages.

There are two kinds of thing worth coming back to, and they differ only in how the question is asked.

The first is something of theirs with an outcome. An outing, a trip, a visit, an appointment, an interview, an exam, a first day, a result they are waiting on, something they have applied for or put an offer on - and anything else of theirs that will have turned out some way by a day you can work out. Those examples are illustrations, not a list to match against: the test is whether there will be an answer to "how did that go?" and whether they would be glad to be asked it. Use kind "following_up", and ask about the thing.

The second is how they are - unwell, exhausted, low, hurt, or under real strain. Use kind "wellbeing", and ask after the person rather than after the event.

The subject is the thing itself in their own words, short and recognisable, the way they would refer to it if they brought it up again: "the visit to National Harbor", "the flat application", "Thursday's exam". The question is what to ask when the time comes, written as an instruction and as one plain sentence: "Ask how the visit to National Harbor went.", "Ask whether they heard back about the flat.", "Check in on how they are feeling after being unwell."

Give happens_in_days as the number of whole days from today until the thing itself happens - 0 for today, 1 for tomorrow, and for a named day count the days from today to that day. For a longer trip, count to the day it ends. Give -1 when there is no single day it happens on: a result they are waiting to hear, an illness, anything with no date of its own. Do not add anything to it for the sake of asking afterwards; that is done for you.

Set after_days to when the question should arrive: after an evening out, the morning after; after a day trip, the next day; after a longer trip, the day after it ends; after something they are waiting on, once the answer would plausibly have come. If they do not say when, and it sounds like it is happening now or today, ask tomorrow. If it is further off than about six weeks, or you cannot work out when at all, answer false - a question that arrives at the wrong time is worse than no question. For a wellbeing check-in ask after a day or two, not the same evening.

These are not it, and the answer for them is false. A question they asked, a fact about themselves, a plan with no time and no shape, an opinion, small talk, a task they gave the assistant, and anything about how the assistant works. A mild passing remark is not a wellbeing check-in, and someone who says they are a bit tired but fine has told you they are fine; the bar is something a person would be touched to be asked about two days later. Someone else's plans, someone else's health and someone else's news are not theirs, however serious - a relative's operation is the relative's, and asking about it is not this. Never treat a recommendation the assistant just offered as something they are doing; wait until they say they are doing it.

If a list of things already waiting is given and this message is about one of them, answer false, however differently it is worded this time - unless it changes it. When the message says one of those things is off, has been called off, fell through, has already happened and been told about, or has moved to a different time, copy that thing's subject into calls_off exactly as it appears in the list. Leave calls_off empty in every other case. If the thing is simply off, that is all: answer false and name it. If it has moved, name it and also answer true with the new timing, so the old date is dropped and the new one takes its place.

The hour is when the question should arrive in their local time, between 9 and 21. Late morning suits a follow-up about an evening out; early evening suits a wellbeing check. Return only the required JSON.
