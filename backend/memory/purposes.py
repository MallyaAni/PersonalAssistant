"""Stable purpose labels shared by memory writers and lifecycle cleanup."""

# Marks semantic entries derived from image analysis rather than user-stated facts.
VISUAL_ANALYSIS_PURPOSE = "visual_artifact_analysis"

# Marks a standing preference - what someone likes, avoids, or wants - as
# distinct from a plain fact about them. Recommendation turns select on this
# rather than on embedding distance, because distance cannot separate them:
# measured 2026-08-30, "prefers metro-connected venues" sits at 0.371 from
# "what events are happening this weekend" while an unrelated question about
# Peru sits at 0.499 from the same memory.
PREFERENCE_PURPOSE = "user_preference"

# Marks a hard constraint - an allergy or dietary restriction, an
# accessibility need, a budget cap, something they must never be sent or
# shown. A preference reorders results that already answer the question; a
# constraint removes a result that violates it. The classifier that already
# says whether a fact is a preference says whether it is this (D7 of the
# platform plan, 2026-09-05).
CONSTRAINT_PURPOSE = "user_constraint"

# Purposes that describe a person's taste or limits rather than a fact or an
# image: what a recommendation turn reads about them.
PREFERENCE_PURPOSES = (PREFERENCE_PURPOSE, CONSTRAINT_PURPOSE)
