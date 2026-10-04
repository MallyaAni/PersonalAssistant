# AAOI entry episode: September 28

Read-only audit on October3; no provider requests, model fits, scoring, account
replay, orders or source-data changes. Objective: identify the actual episode
behind the operator's concern about buying before a substantial intraday decline,
and preserve stock-volatility/price-structure evidence without choosing a
hindsight bottom or a new percentage trigger.

## Observed chronology

VERIFIED cached daily history for September21–October2: September28 is the
session that traded near95. Prior Yahoo close101.4000015; daily low93.6200027,
7.67258% below that close; final daily close96.8199997. October1 low97.77 and
October2 low106.32 do not match this episode. A price of95 itself is about6.31%
below101.40; the roughly7% description matches the deeper session low.

September28 raw SIP bars below are indexed by their New York **completion** time.
The OHLC low is observable only after its full bar, never at the bar's start.

| Completed at ET | Close | Bar low |
| --- | ---: | ---: |
| 09:45 | 98.81 | 98.35 |
| 10:00 | 97.20 | 97.05 |
| 10:15 | 96.38 | 96.00 |
| 10:30 | 96.75 | 96.3593 |
| 10:45 | 94.87 | 94.71 |
| 11:00 | 94.41 | 93.75 |
| 11:15 | 94.405 | 94.30 |
| 11:30 | 94.875 | 93.62 |

The stored IEX latch reports an opening price100.10, buy level99.099, and the
first dip trigger at the09:30-start bar's close98.61, received09:45:27ET.
This differs from the SIP opening100.09/first close98.81: preserve both domains.

The stored paper journal reports a **9-share buy at100.601111, filled09:34:31.403532ET
on September28**, from the September25 nightly plan. Its decision was
September25 23:45:08.584665Z; order creation23:45:08.708148Z and subsequent
submissionSeptember28 08:01:00.085529Z. This fill preceded the first completed
15-minute dip observation. It was a queued day order, before adoption of the
current intraday execution path. It does **not** show that the current1% executor
ignored an available completed-bar signal. This is paper evidence, not the
operator's personal broker fill.

## Original bytes and publication

All paths below are relative to `/home/animallya96/deploy/anios/data/market/`.
Read bytes were checked unchanged after parsing; mutable journal/latch hashes
identify the audit observation, not an immutable historical publication chain.

| Original file | SHA256 | Publication / source |
| --- | --- | --- |
| `bars_15m_sip/asof=2026-09-28/AAOI.parquet` | `694810d05e775e7a78b63f856b572b7548e1b541701a746fba82d3c34627894e` | Raw SIP15Min; fetchedSeptember29 01:39:50.437122Z; revision`e8fafc6ef06dcc0e77c9d256b222a8b9cde04563` |
| `bars_15m_sip/asof=2026-09-25/AAOI.parquet` | `7468942e95d2922c39d5251c8a8ebb626fe69108f739a72cbe4bbe78674a1e75` | Raw SIP15Min; fetchedSeptember27 04:57:56.455617Z; revision`f6228b7f3bfaf24ec667a096c72dd89841eb4e65` |
| `bars/asof=2026-09-25/AAOI.parquet` | `434da6f1aefb08644cd26116778e4a7f8054480b0e9a63ed9af9ab033152f211` | Yahoo daily source_timeSeptember25 23:30:03.664258Z; complete_throughSeptember25 |
| `bars/asof=2026-09-28/AAOI.parquet` | `40a162bf507a35ea926a1c5c12368bb830cdb22e49a6b0afa423a0c2e948cc4e` | Yahoo daily source_timeSeptember28 23:30:02.393805Z; complete_throughSeptember28 |
| `desk/asof=2026-09-25/desk.json.879abc56` | `72e994ce66223b9a7cea3a865f4bf90a6473543235b31305847ce92f7f1c50fd` | Original writtenSeptember25 23:45:53Z; code`879abc56`; AAOI A+ |
| `desk/asof=2026-09-25/desk.json` | `cf37919c5f588d74253db4a58ef68d9836fd3753aa6fc4f2db2b43a27645458a` | Re-recordedSeptember28 03:21:26Z; provenance code`508c66c9`;23 grades changed, AAOI remained A+; original paper receipt carried forward |
| `desk/entry-timing/2026-09-28.json` | `1be282f05ba4071379920e0e9b89cb9e6498496950365359913ddf90e38a2625` | Trigger seen09:45:27ET; final file updated20:15:28.691957Z; no per-latch source revision |
| `paper/state.json` | `7014c61657f8c4dd4053947d46bd9f21ca88a944bf7597f596aedb2518c323ce` | Audit-time journal containing the9-share receipt and original execution clocks |

Both SIP partitions have26 complete regular15-minute bars plus a16:00-start
row; exclude that additional row from regular closes or fill proxies. Prior
SIP last regular close101.34 is distinct from Yahoo official close101.40.
Daily OHLC is the store's split-adjusted basis; SIP is raw. Do not infer a ratio
or silently combine these histories. September25/28 actions files both hash
`a22c779da95248564cf2505eef8e604e13e6595b9a91b6b5e073331a80347b16`, with
no dated actions and no publication metadata: retrospective absence only.

The re-recorded grade set became available before Monday's market open but
**after Friday's original planning decision**. Use the original record to
reproduce that decision; do not substitute later grades or analyst inputs.
The September28 daily partition likewise cannot enter that day's earlier
intraday decisions. SIP fetched after close supplies outcomes, not original
historical provider-receipt clocks.

## Minimal legitimate fixture and remaining boundary

Preserve the original September25 record/daily context, prior and current raw
SIP partitions, action bytes, IEX trigger receipt and paper-fill journal. Expose
only completed prefixes in chronological order; test that later bars cannot
revise earlier features or decisions. Preserve the original intended basket,
pre-sale cash/whole-share ownership and first-attempt rules for any funded
comparison. Do not invent its missing account state from the AAOI order alone.

This is a selected **retrospective episode regression**, not untouched OOS edge
evidence. A conditional replay of today's timing rule would be counterfactual:
that rule did not execute this historical9-share order. No September28 raw
1-minute series or full contemporaneous IEX response chain was located in the
standard market cache. The latch retains one trigger/receipt, not the entire
per-clock feature, quote/spread or model-completion history. Those original
receipts, actual full basket/funding state and later executable opportunities
are required for exact current-live timing claims. Neither a bar low nor an
assumed midpoint is a proven executable fill.

The daily one-session learner, including the held-B extension, observes the
previous completed close and plans an official-next-open proxy. Its daily
volatility and covariance can size risk, but it cannot condition on this day's
evolving15-minute range, continuation or reversal. Learned daily holding exits
must not be described as solving this intraday entry-point problem. Production
timing and reliable stock-conditioned intraday advantage remain UNVERIFIED.
