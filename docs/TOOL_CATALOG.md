# What the assistant can do

Generated from `backend/tools/registry.py` by
`python -m backend.cli.generate_tool_catalog`. Do not edit by hand: a test
compares this file against a fresh render, so an edit here is a failure there.

Every row below is one tool the router may call for a turn. The router is
offered them all and picks at most one per step; calling none is a normal
outcome and means the turn is answered as an ordinary reply.


## How to read the columns

- **Loaded** says when the tool's full definition is put in front of the
  router. `always` is the handful most turns actually use. `with a picture`
  loads only when one is in view, since the interface state already decides
  whether the tool can be used. `catalogued` means it is represented by a
  one-line index entry and fetched on demand, which is what keeps accuracy
  from falling away as this list grows.
- **Arguments** are what the model must fill in. A tool that takes a subject
  or an instruction is one the model has to state its reading of the request
  for, which is what makes a mistaken choice visible before the turn is spent.


## Searching the web

`search_web` is not a built-in row. It is assembled from whichever search server is wired at the time, so it is always offered and never catalogued, and its arguments come from that server rather than from this repository.


## Diagrams

| tool | what it does | arguments | loaded |
| --- | --- | --- | --- |
| `create_diagram` *(needs the diagram service)* | Draft a technical diagram (flowchart, architecture diagram, sequence, state, class, or entity-relationship) | `subject` | catalogued |


## Documents

| tool | what it does | arguments | loaded |
| --- | --- | --- | --- |
| `create_document` | Write text into a file the user can keep, open, and share: a PDF or a Word document | `body_markdown`, `format`, `title` | catalogued |
| `edit_document` | Rewrite a Word file the user shared earlier in this conversation with revised text, keeping the file's own look - its fonts, colours, header, logo, and page setup - and hand the updated file back | `body_markdown`, `format`, `title` | catalogued |


## Memory

| tool | what it does | arguments | loaded |
| --- | --- | --- | --- |
| `search_history` | Search everything the user and you have said to each other, across all past conversations | `query`, `since`, `until` | always |


## Pictures

| tool | what it does | arguments | loaded |
| --- | --- | --- | --- |
| `discuss_image` | Talks about the picture currently in view without changing it or putting it back on screen: an opinion ('which hat do you like better for this outfit?'), a comparison, advice, or a question about what is in it | `about` | with a picture |
| `edit_image` | Change the picture currently in view, including adding labels or annotations to it | `instruction`, `restages_the_scene` | with a picture |
| `generate_image` | Create a brand-new picture from a text description, when the user asks for an image, picture, drawing, or artwork to be made | `depicts_a_person`, `prompt` | catalogued |
| `show_image` | Show or send again a picture the user already has here - one made, edited, or uploaded earlier in this conversation or their history - when they ask to see it, bring it back, pull it up, look at it again, or have it sent to them | `which` | with a picture |


## Presentations

| tool | what it does | arguments | loaded |
| --- | --- | --- | --- |
| `delegate_to_presentation_agent` *(needs the presentation service)* | Hand off to the specialist that builds slide decks | `subject` | catalogued |


## Scheduling

| tool | what it does | arguments | loaded |
| --- | --- | --- | --- |
| `manage_check_ins` | Check-ins: the assistant coming back later, on its own, to ask how something went - a trip, an interview, a hard week | `after_days`, `hour`, `kind`, `mode`, `question`, `subject` | catalogued |
| `manage_tasks` | Acts on a reminder or scheduled message this person already set up | `cadence`, `hour`, `instruction`, `minute`, `on_date`, `operation`, `weekday`, `which` | always |
| `schedule_task` | Set something up to happen later or on a schedule: a reminder, a daily or weekly message, a recurring check or lookup, anything they want done at a stated time rather than now | `cadence`, `hour`, `instruction`, `minute`, `on_date`, `weekday` | always |
| `scout_schedule` | Sets or changes when Scout's own sweep runs - the recurring check for things happening near this person, their events digest | `cadence`, `hour`, `minute`, `operation`, `weekday` | catalogued |


## Skills

| tool | what it does | arguments | loaded |
| --- | --- | --- | --- |
| `manage_skills` | List or delete the skills they already taught | `operation`, `which` | catalogued |
| `save_skill` | Save a named routine the person can invoke later by name or by meaning: choose it when they are teaching one - 'when I say morning brief, give me the weather and my tasks', 'make a skill called weekly wrap-up that...', 'remember this as my standup routine' | `instruction`, `name` | catalogued |


## Skills

A person's saved skills are offered as tools too, one per skill, named `skill__<name>`. They are not listed here because they differ per person: `save_skill` creates one and `manage_skills` lists or removes them.
