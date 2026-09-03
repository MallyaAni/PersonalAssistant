# Check-ins: coming back to something the person only mentioned

How the assistant asks "how was National Harbor?" two days after an outing it
was never asked to remember, and why that costs one table column, one prompt
and no new worker.

The short version: a check-in is an ordinary one-off scheduled task. The only
new thing is the judgement that decides to arm one. The decision and its
reasoning are [ADR 0019](adr/0019-a-check-in-is-a-scheduled-task.md).

## Off until asked (2026-09-02)

People did not like being checked on unasked, so nothing here runs for
anyone who has not asked for it. The switch is one preference on the
person's profile (`preferences.check_ins`, visible and clearable like any
other), read by `conversation_service._check_ins_enabled` before the
judgement is even started; an unreadable profile counts as off, because the
safe mistake is to stay quiet. A room has its own switch under the group's
id, so a member can ask for check-ins in the room without changing their
own.

Asking is a skill. The shipped pack `skills/check-ins.md` ("Check-ins") is
offered to everyone and reaches the `manage_check_ins` tool
(`backend/tools/manage_check_ins.py`), which the router can also choose
directly:

| Mode | The ask | What happens |
| --- | --- | --- |
| `on` | "from now on, check in on me about the things I mention" | the preference is set; from the next turn the judgement runs as described below |
| `off` | "stop checking in on me" | the preference is cleared and every waiting check-in is dropped - stop means stop, not "after these" |
| `once` | "check in with me on Friday about how the interview went" | one check-in is armed for the named thing, through the same `arm_check_in` and under the same limits (three waiting, no duplicate subject, a civil hour, never wellbeing in a room); the habit stays as it was |
| `status` | "what are you going to ask me about?" | on or off, and what is waiting |

The tool acts only on an ask. Its parser reads the message and returns no
action unless the words contain one (check in, follow up, keep tabs, ask
me, stop checking): a statement about the person's day, even right after
they asked for check-ins, is left to the judgement. Decided in code because
the router sent exactly that statement to the tool 3/3 after the
description said not to (2026-09-02).

The outcome travels in the same record a scheduled task uses, rendered by
`graph._render_check_in_outcome`, so the reply says what is now set rather
than guessing - and says it as what it is to the person ("I'll ask on
Friday"), never as a task or an automation. Pinned by
`test_manage_check_ins_tool.py` (the gate, the modes, the limits),
`functional/test_check_in_request_behaviour.py` (the router and the reply
on the real models), and the sweep's four check-in journeys (nothing armed
while off, armed once asked, one by name, stop).

## Why it works this way

The operator asked for this on 2026-08-30: "it would be nice to have the agent
check in on something if it knows for example how was the visit to national
harbor? (this is easier since it knows the time of the event) or if the user
isnt feeling well like an occasional check in on how they're doing".

Everything a check-in needs already existed. `scheduled_tasks` stores a `once`
cadence with a calendar day and a local hour. `backend/workers/task_runner.py`
claims a due run under a lease, converses as the person in the task's own
thread, and delivers on the channel the task was made from, including a group
room. A firing with nothing to say has a silence token. A task the person no
longer wants is cancelled by naming it in their own words, through the picker
that already backs "cancel the weather one".

So the only thing missing was noticing. The router cannot do it: the router
fires on what a person *asks for*, and nobody asks to be checked on. This
reads what they merely mentioned.

## The path, step by step

1. **The turn runs as usual.** Nothing about the reply changes, and nothing
   here can change it. Nothing below runs unless the person has asked for
   check-ins (the section above).
2. **A judgement runs alongside the memory proposal**
   (`backend/core/checkin.py`, started as a task in
   `conversation_service._arm_check_in` so the two calls overlap and the turn
   costs no extra wait). One constrained call at temperature zero on the
   routing model returns whether to come back to this, what to call it, how
   many days out, and at which local hour.
3. **The caller decides whether it is allowed to**
   (`backend/services/checkin_arming.py`). This is where every limit lives.
4. **A one-off task is created** through `ScheduledTaskRepository.create` with
   `kind="checkin:following_up"` or `"checkin:wellbeing"`, on the person's own
   calendar day in their own timezone - and never on a slot that has already
   passed, since `next_run_at` returns a past one-off instant as it stands.
5. **The runner fires it** like any other task and texts the result. The
   stored instruction is one plain sentence - "Ask how the visit to National
   Harbor went." - because that is what the person sees when they list what
   is scheduled. How a check-in should be worded (short, warm, no searching,
   no announcing itself as an automation) is attached by the runner from the
   task's kind (`task_runner._asked`), so nobody has to read directions
   addressed to a model in their own reminder list.

## What is open on purpose

The two examples asked for were an outing and an illness. They are not the
specification, and three parts of this are deliberately not enumerated so
that a situation nobody thought of is still handled:

- **The model writes the question.** "Ask whether they heard back about the
  flat." is not "Ask how X went." with a different X. A template per category
  silently caps what can ever be followed up at the categories someone wrote
  first.
- **There are two kinds, and they describe what governs the rules rather
  than what happened.** `wellbeing` is separate because it alone is rationed
  and alone must never be asked in a room; `following_up` is an outing, a
  trip, an appointment, an interview, a result someone is waiting on, and
  whatever else has an outcome. Adding a situation is not a migration.
- **A plan called off calls off its check-in.** The worst thing this feature
  can do is not silence - it is asking how a trip went that the person had
  already said was cancelled. The same call that notices a plan notices
  "we bailed on Saturday" and "Harbor moved to next weekend", names which
  waiting thing it means, and the caller drops it - and arms the new date in
  its place when it moved rather than ended. Only a subject copied back
  exactly from the list supplied is honoured, so a paraphrase takes nothing
  down, and a reminder can never be taken down at all.
- **"Have I already asked about this?" is asked, not computed.** The
  judgement is handed the subjects already waiting and answers false when
  this message is the same thing worded differently. "That Harbor thing on
  Saturday" and "the visit to National Harbor" are one outing, and no
  comparison in code is going to know that. The word comparison in
  `checkin_arming` remains as a backstop for the near-identical case.

## What is decided in code, and why none of it is in the prompt

The judgement sees one message and remembers nothing it has already proposed.
Left to itself it would arm something most turns. Each of these is a query or
a comparison, not a sentence a model is asked to honour:

| Limit | Value | Why |
| --- | --- | --- |
| Waiting at once | 3 | A chatty afternoon otherwise fills next week with questions. |
| Wellbeing spacing | 7 days | A second "how are you feeling?" in three days reads as nagging. |
| Same subject twice | refused | Mentioning an outing twice should be asked about once. |
| Sensitive kinds in a room | refused | A room may be asked how the trip went; how one member is feeling is theirs to tell, and the room may include people who were not in the conversation where they said it. |
| No timezone | refused | Guessing one is how a check-in arrives at 4am. |
| Days ahead | 0-45, refused beyond | Clamping a wedding next spring into the window does not make a smaller mistake, it asks "how was the wedding?" months early. |
| Hour | 09-21 | Nothing should propose 3am in the first place. |

The subject is stored on the row. It used to be recovered by matching the
front of the instruction against the templates that wrote it, which tied two
functions together through prose - reword the question and the duplicate
check quietly stops working. Now that the question is written rather than
chosen, there is no template to match against at all.

`kind` is a column rather than something read out of the instruction, so the
cap is a query and reminders the person asked for are never counted against
it. Someone with five reminders can still be checked on. It carries which
sort of check-in too, so the wellbeing cooldown compares a stored value
rather than matching a prefix on an instruction that gets reworded the first
time anyone improves its wording.

## What can go wrong, and what happens

One distinction is carried by *how* a check-in goes away rather than by a
column recording why. A person who cancels the question ("cancel the harbor
one") disables the row, and the duplicate rule reads disabled rows, so
mentioning the outing again does not quietly bring the question back - they
said stop asking. A plan falling through removes the row instead, because
that says nothing about wanting to be asked, and a trip that is back on next
week deserves its check-in back.

## What it does not do

- **One check-in per message.** "National Harbor on Saturday and the dentist
  on Monday" arms the first, not both. Graceful rather than wrong, and the
  alternative - several armed from one sentence - is the intrusive failure
  this feature is mostly written to avoid.
- **Nothing is armed from what the assistant suggested**, only from what the
  person says they are doing. Saying yes to a suggestion counts, because the
  judgement is given the previous reply and can resolve "that one".
- **Nothing sensitive is armed in a room.** A shared outing is followed up
  there like anything else; a `wellbeing` check-in never is.

| If | Then |
| --- | --- |
| The judgement call fails or times out | No check-in. The turn is unaffected; a check-in is a courtesy. |
| The task repository is unreadable | No check-in, reason `unreadable` in the trace. |
| A check-in fires and the person has moved on | They cancel it by name, like any reminder. |
| A firing check-in mentions something new | Nothing is armed: the whole classification branch is skipped for a scheduled task, so a thread cannot ask after itself forever. |

## Status

| Part | State |
| --- | --- |
| Off until asked; the Check-ins skill and `manage_check_ins` (on, off, once, status) | Built 2026-09-02, pinned by `test_manage_check_ins_tool.py`, `functional/test_check_in_request_behaviour.py`, and the sweep journeys |
| The judgement and its prompt | Built, pinned by `functional/test_check_in_proposal_behaviour.py` |
| What a firing actually says | Built, pinned by `functional/test_check_in_message_behaviour.py`, which also holds the router to choosing no tool for a firing |
| The limits | Built, pinned by `test_checkin_arming.py` |
| `kind` column and migration | Built (`20260830_0013`) |
| One-to-one threads | Built |
| Rooms, non-sensitive kinds | Built: a shared outing is followed up in the room |
| Rooms, wellbeing | Deliberately refused; see the table above |
| Situations with no template | Built: the question is written per check-in |
| Asking about something Scout suggested and the person accepted | Not built. Today a check-in follows what the person says they are doing, not what they said yes to. |
