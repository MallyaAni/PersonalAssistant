name: checkin/propose
used by: backend/core/checkin.py
runs on: the routing model (schema-enforcing engine)
pinned by: functional/test_check_in_proposal_behaviour.py

What this is for, in the operator's words on 2026-08-30: "it would be nice
to have the agent check in on something if it knows for example how was the
visit to national harbor? (this is easier since it knows the time of the
event) or if the user isnt feeling well like an occasional check in on how
they're doing".

The failure this prompt is written against is not missing a check-in. It is
arming one every turn. This call sees a single message with no memory of
what it has already proposed, so a prompt that leans towards yes produces a
thread that asks after everything the person ever mentioned. Reluctance is
the default and the bar is high: something happened or will happen at a
knowable time, or the person said something about their own state that a
friend would follow up on. Everything else returns false.

The caller enforces every limit that keeps this civil - how many may be
armed, how close together, how far ahead, which hour - in code, so this
prompt never has to be trusted with them. It only decides whether the thing
is worth coming back to at all, and what to call it.

===== PROMPT BELOW — everything under this line is sent to the model =====

Decide whether something in this message is worth quietly coming back to later. Almost nothing is. Answer false unless one of two things is true.

The first is that the person mentions something they are doing, or have just done, that a friend would ask about afterwards - an outing, a trip, a visit, an appointment, an interview, an event they are going to. Use kind "event". The subject is the thing itself in their own words, short and recognisable: "the visit to National Harbor", "the dentist appointment", "the Chicago trip". Set after_days so the question arrives once it is over and they have had time to get home: the morning after an evening out, the day after a day trip, the day after the last day of a longer one. If they say when it is, count the days to it from today and add one. If they do not say when, and it sounds like it is happening now or today, ask tomorrow.

The second is that the person says something about how they are - unwell, exhausted, low, hurt, or under real strain. Use kind "wellbeing". The subject is what they said in a few plain words: "not feeling well", "the migraine", "a rough week". Ask after a day or two, not the same evening.

Answer false for everything else. A question they asked, a fact about themselves, a plan with no time and no shape, an opinion, small talk, a task they gave the assistant, anything about how the assistant works, and anything that is already going to be handled by a reminder they asked for. Passing mild remarks - tired, busy, hungry, a slow morning - are not a wellbeing check-in; the bar is something a person would actually be touched to be asked about. Someone else's plans or someone else's health are not the person's own, and are false. Never treat a recommendation the assistant just offered as something they are doing; wait until they say they are doing it.

The hour is when the question should arrive in their local time, between 9 and 21. Late morning suits a follow-up about an evening out; early evening suits a wellbeing check. Return only the required JSON.
