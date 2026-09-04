name: memory/persona
used by: backend/core/persona.py -> characterize()
runs on: the reply model (MAIN_LLM_MODEL), once per distinct interest set, cached on the set itself
pinned by: functional/test_persona_behaviour.py
placeholders: none
2026-09-04: added. Twenty interests at equal strength could not say that seven of them meant "social dancer", so a search query got six near-arbitrary tags and the reply prompt banned the list outright rather than dose it.

Turns a list of interests into a description of a person.

What breaks when this is wrong:
  - Repeating the list back as prose. The point is to say what the list
    means, not to read it aloud with commas.
  - Inventing. Nothing may be said that the list does not support - not an
    age, a job, a family, a budget, or a personality trait nobody listed.
  - Losing the specific things. "Likes going out" has thrown away salsa.

===== PROMPT BELOW — everything under this line is sent to the model =====

Describe this person in one or two sentences, from what they like.

Group what belongs together and say what it means. Six entries about salsa, bachata, swing and line dancing are one fact - they are a social dancer - and saying it once, with a couple of the specific dances named, is worth more than listing all six. Do the same for the rest: games, the outdoors, food and drink, browsing and markets.

Say how they like to choose when the list tells you. "Exploring new things", "trying new places" and "unique local events" mean someone who would rather do something new than the same night again; their absence, or an interest in the familiar, means the opposite. This is worth a clause, not a sentence.

Keep every specific thing that would help someone recommend them an evening: name the dances, the drinks, the games. A description that says "enjoys social activities" has lost everything that made it worth writing.

Write it as someone who knows them would say it, in plain words, under forty. Say nothing the list does not support - no age, job, family, budget, or trait nobody listed. If the list is too thin to characterize, describe what is there and stop.
