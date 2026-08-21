name: vision/search_grounding
used by: backend/services/visual_search_grounding.py
runs on: the routing model (schema-enforcing engine)

Whether an image warrants an outbound web search and what to search for.

===== PROMPT BELOW — everything under this line is sent to the model =====

Below is a description of an image somebody uploaded, and the question they
asked about it. Decide whether answering that question well needs a web search.

Search when the question turns on identifying a specific product, model, brand,
place, person, plant, animal, or text whose meaning you would have to look up -
anything where being out of date or mistaken about a real-world fact would make
the answer wrong. Naming something confidently from memory is exactly the
failure a search prevents.

A question asking you to judge, advise, warn, or recommend still needs the
search whenever that judgement depends on knowing what the thing actually is -
whether a mushroom is safe to eat, whether a snake is venomous, whether a
vintage is good, whether a part will fit. Identify first, then judge. The test
is simple: if learning the object's real name could change your answer, look it
up rather than reasoning from appearance.

Do not search when the description already contains everything the question
needs - counting, comparing, reading values, judging colour or composition,
giving an opinion about what is visible, or any question answerable from the
description alone. A question is pure opinion only when it is about what is
visible - colour, arrangement, mood, style, composition - and its answer would
not change if you learned what the object was called.

When you search, write the query from the distinctive visible details, not from
a guess at the answer: describe the object's form, markings, colour, and any
readable text, so the search can identify it rather than confirm a hunch.
