name: reply/handed_off
used by: backend/agents/graph.py -> _turn_kind (context["handed_off"])
runs on: the reply model, appended to reply/system when this turn's loop stopped on its budget or ceiling and the rest was handed to a durable run
pinned by: functional/test_handed_off_wording_behaviour.py
placeholders: none

When a turn's step loop runs out of wall clock or steps with the router still
naming work, the application creates a durable run to finish it and records
the hand-off in the turn context under "Handed off". The reply model has to
say two things and avoid a third: that the steps already taken happened (they
did, and their results are in the context), that the rest is being finished
in the background and the person will be told, and never that the whole
request is done. Without this block the model, shown a partial set of
results, either confirmed the whole thing or apologised for not finishing
something that is in fact being finished.

What breaks when this is wrong:
  - "Done" over a request that is half done: the person acts on a result
    that is not there yet.
  - "I couldn't finish": the person asks again, and two runs do the same work.
  - Inventing what the remaining steps will find: the run has not run.

===== PROMPT BELOW — everything under this line is sent to the model =====

This turn ran out of time or steps before everything the message asked for
was done, and the application has handed the rest to a background run that
will finish it and tell them when it has. The turn context records this
under "Handed off", with the steps that were completed in this turn and the
steps still to come. Answer from what the completed steps found, as normal.
Then say, in one plain sentence, that the rest is being finished in the
background and they will hear when it is done - name what remains only as
the record names it. Do not say the whole request is done, do not apologise
for the part still running, and do not describe or guess at what the
remaining steps will find.
