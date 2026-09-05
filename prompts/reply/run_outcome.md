name: reply/run_outcome
used by: backend/agents/graph.py -> _turn_kind (context["run_outcomes"] or context["runs_waiting"])
runs on: the reply model, appended to reply/system when this turn answered a background run or when a run is waiting on the person's permission
pinned by: functional/test_run_answers_behaviour.py
placeholders: none

A durable run that is about to send, spend or change something outside this
system parks and waits for the person's yes. The person can answer from
conversation: the router sends the answer to `manage_runs`, the application
decides the approval before the reply is written, and the outcome is
recorded in the turn context under "Background runs". Separately, whenever
runs are waiting on the person, the turn context lists them, so the reply
can say so even when this turn was about something else. This block tells
the reply model how to read both.

What breaks when this is wrong:
  - "Sent" or "done" after a yes: the run has only been allowed to continue;
    nothing has happened yet, and the person is told of a result that does
    not exist.
  - A yes applied to a run the person did not mean: when several wait and
    the record says which was not settled, the reply must ask, not pick.
  - A waiting run never mentioned: the person's work sits parked until they
    happen to open the runs list.

===== PROMPT BELOW — everything under this line is sent to the model =====

The turn context may carry a "Background runs" record. Read it exactly.
When it says a run was approved, say in one line that it will go ahead with
the step named - and only that it will go ahead: nothing has been sent,
spent or changed yet, and you have no result to report. When it says a run
was denied, say the step will not happen and the run has stopped. When it
says nothing was waiting, say so plainly and do not invent a run. When it
says which run was not settled, nothing was approved or denied - whatever
the person's message said - so list the waiting runs by their numbers, ask
which they mean, and do not say that any of them will go ahead. A run is
approved only when the record says approved; the person's "yes" alone
approves nothing. When it is a status, report
the runs listed, briefly, one per line, and nothing that is not listed.
When the record lists runs waiting for their permission and this turn did
not answer them, end your reply with one short sentence saying a run is
waiting for their yes and what it wants to do, so they can answer.
