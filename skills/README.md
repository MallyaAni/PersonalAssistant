# Shipped skills

A skill is a named routine the assistant runs when a message asks for it by
name or by meaning. People teach their own in conversation ("when I say
morning brief, give me the weather and my tasks"); the files here are the
ones that ship with AniOS and are offered to everyone.

One file per skill:

```
---
name: Quick brief
description: A three-line brief on any topic the person names.
---
The instruction that runs, written to the assistant, in full.
```

`description` is what the router reads when deciding whether a message
invokes the skill, so it should say what the skill is for. The body is what
runs, as the turn's instruction, with every ordinary tool (search, weather,
images, scheduling) available to it. A user-taught skill with the same slug
takes precedence over a shipped one.
