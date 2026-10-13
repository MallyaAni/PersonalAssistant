# Grade direction and learned sizing

The human requested restoration of the previous grade-based entry/exit rules,
with the learned models used for sizing and timing rather than replacing the
directional signal. This is a behavioral contract, not a claim of higher returns.

New policy `grade-led-learned-sizing/1` preserves the original model-only policies
and their immutable histories. A/A+ permits entry; a held stock below A exits.
Missing grades protect holdings. An eligible unheld stock remains a BUY signal
when risk, model size, whole-share rounding, funding or execution timing blocks
an order. Signals carry their grade, previous grade, observed session and basis.
They are not fills. Eligible held stocks may be resized, but a model zero does
not independently authorize a full exit: those holdings are preserved until a
grade exit or existing explicit event policy. Preserved capital is not available
to finance purchases. Existing account, cash, costs, name caps and whole-share
guards remain mandatory; sales never count as available funding before settlement.

Ticker charts default to dated grade signals. The original latest-strategy
model-only counterfactual remains a separately labeled research layer. Restoring
an original historical grade signal never invents a hybrid-policy fill or rewrites
the original paper account. Saved/recalculated grade provenance stays explicit.
No original model is retrained, no past actual day is rerun, and no performance
claim follows from implementing this contract. Fresh ordinary paper acceptance
is required after installation; private fixtures are not that acceptance.
