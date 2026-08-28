name: deck/slide
used by: backend/agents/deck/prompts.py -> per-slide writing
runs on: the presentation role (PRESENTATION_LLM_*)
pinned by: functional/test_deck_prompt_behaviour.py

Writes one slide's content from the approved outline.

===== PROMPT BELOW — everything under this line is sent to the model =====

Keep the supplied title, purpose, and layout exactly; the deck's shape was already decided. Supply whatever that layout needs. This slide advances the deck rather than summarising it: write only what belongs to this beat, do not repeat what an earlier slide covered, and carry the beat into visual_prompt so any image matches this point in the arc rather than the subject in general.
