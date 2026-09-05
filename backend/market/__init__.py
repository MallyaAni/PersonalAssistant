"""Daily market data, and the measurements a model must beat.

The flow: `universe` names the cross-section; `yahoo` fetches each name's
completed sessions and corporate actions; `store` keeps every fetch as an
immutable as-of partition; `snapshot` runs and audits a refresh; `panel`
aligns the stored histories onto one calendar; `baselines` and `harness`
measure known cross-sectional effects on that panel out of sample; and
`windows` turns the same panel into raw sequence tensors for a model. A
model earns its place only by beating the baselines in the harness, net of
costs, on the same panel.
"""
