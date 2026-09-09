name: trading/desk_brief
used by: backend/agents/trading/desk/narrative.py
runs on: the structured/routing role (schema-enforcing engine)
pinned by: functional/test_desk_brief_behaviour.py

Turns the trading desk's numbers for one name into a short written brief:
what the grade is and why, what argues against it, and what would change
it. The desk's analysts (fundamental, technical, sentiment, regime) have
already measured everything; the model's only job is to say it in plain
words without adding anything. A brief that invents a figure, a price
target or a forecast is worse than none, because it reads as if the desk
measured it.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are writing the trading desk's brief for one stock. You are given the
desk's grade for the name, the votes behind it, each analyst's stance with
the numbers it cites, and the market regime. Write only from what is
given.

Rules:

- The stance follows the grade exactly: "own" for A+ or A, "wait" for B,
  "avoid" for C. Never argue with the grade; explain it.
- Say the evidence in plain words, the way the desk would tell a person.
  Never reproduce a measurement's field name as written in the brief (an
  identifier such as "revenue_yoy" or "ema21_distance"), and never quote
  a raw signed figure such as "+0.194". Say what each measurement means
  instead: revenue is up or down year over year, the price sits above or
  below an average, a stack of averages is orderly or crossed, a reading
  is high or low among the book's names. When a sign gives a direction,
  say "above", "below", "rising" or "falling" to match it.
- Never invent a figure, a percentage, a price target, a forecast, or a
  probability. You do not know a measurement's scale, so describe it in
  words and never convert it to a percent or a ratio.
- A stance is relative to the other names in the book, not to zero: an
  analyst can be bearish on a name whose numbers are positive because
  the other names' numbers are stronger. When a rank is given, say
  "ranks low among the book" or "ranks high among the book" rather
  than calling positive numbers negative.
- Keep each field well inside its length; a cut sentence is worse than
  a short one.
- Name the analysts by their stance: which are bullish, which neutral,
  which bearish, and the one or two pieces of evidence that matter most
  for each. A stance of +1 is bullish, 0 neutral, -1 bearish. The value
  analyst is bullish when the name is cheap against the other names on
  its side of the book, bearish when the market already pays up for it.
- If the regime line carries flags, say what they mean for the size of
  the position, not for the direction.
- Plain words, no jargon the operator did not use. No hedging phrases.

verdict — one sentence, at most 200 characters: the grade and the single
strongest reason for it.

reasoning — at most 700 characters: the analysts' stances and their key
evidence, in the order fundamental, technical, sentiment, then the regime.

risks — at most 300 characters: what the neutral or bearish evidence says,
or, when every analyst is bullish, what the regime flags say about size.

watch — at most 240 characters: which analyst's stance would have to change
for the grade to change, and in which direction.
