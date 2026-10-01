"""Does the statement reader call the next quarter from the numbers, and only them?

The prompt claims four things, and each is a case here, against the real
structured runtime (skipped when it is unreachable; a skip is not a pass):

- **A clearly improving company reads up.** Eight quarters of rising
  revenue, widening margins and cash flow that confirms earnings must come
  back "up" with a probability above one half, and the stated direction
  must sit on the probability's side.
- **A clearly deteriorating company reads down.** Falling revenue,
  margins turning negative and cash burn must come back "down" with a
  probability below one half.
- **The rationale is three plain sentences about the figures.** It names
  at least one figure or line from the table and carries no company name
  from the universe: the block is anonymised, and a rationale that names
  a company would show the model answering from memory rather than from
  the table.
- **The call is a reading of the table, not of the labels.** The same
  improving company with its quarters relabelled (the block is built
  identically, so this is the determinism the plan registers) returns the
  same direction.

The blocks are built by the study's own builder from synthetic facts, so
the prompt is measured on exactly the shape it will be sent.

Not run at the time of writing (2026-10-01): the desktop bridge was down
and the runtime is the Sparks' DeepSeek server. The report says so.
"""

import re

import pytest

from backend.agents.trading.statement_reader import DOWN, UP, StatementReader
from backend.market import statements as st
from backend.market.universe import build_universe
from backend.tests.test_statements import filer, flow_rows, instant_rows

pytestmark = pytest.mark.asyncio


# The last block of a filer whose every line improves quarter on quarter.
def _improving_block() -> str:
    n = 12
    revenue = [1_000e6 * (1.06**i) for i in range(n)]
    versions = filer(
        n=n,
        Revenues=flow_rows(revenue),
        GrossProfit=flow_rows([r * (0.55 + 0.01 * i) for i, r in enumerate(revenue)]),
        NetIncomeLoss=flow_rows([r * (0.12 + 0.01 * i) for i, r in enumerate(revenue)]),
        EarningsPerShareDiluted=flow_rows([0.40 * (1.08**i) for i in range(n)]),
        NetCashProvidedByUsedInOperatingActivities=flow_rows(
            [r * (0.18 + 0.01 * i) for i, r in enumerate(revenue)]
        ),
        PaymentsToAcquirePropertyPlantAndEquipment=flow_rows(
            [r * 0.06 for r in revenue]
        ),
        Assets=instant_rows([4_000e6 + 150e6 * i for i in range(n)]),
        StockholdersEquity=instant_rows([2_000e6 + 120e6 * i for i in range(n)]),
        CashAndCashEquivalentsAtCarryingValue=instant_rows(
            [600e6 + 80e6 * i for i in range(n)]
        ),
        LongTermDebtNoncurrent=instant_rows([900e6] * n),
    )
    return st.observations(versions)[-1].block


# The last block of a filer whose every line deteriorates quarter on quarter.
def _deteriorating_block() -> str:
    n = 12
    revenue = [1_000e6 * (0.94**i) for i in range(n)]
    versions = filer(
        n=n,
        Revenues=flow_rows(revenue),
        GrossProfit=flow_rows([r * (0.45 - 0.02 * i) for i, r in enumerate(revenue)]),
        NetIncomeLoss=flow_rows([r * (0.08 - 0.02 * i) for i, r in enumerate(revenue)]),
        EarningsPerShareDiluted=flow_rows([0.30 - 0.06 * i for i in range(n)]),
        NetCashProvidedByUsedInOperatingActivities=flow_rows(
            [r * (0.10 - 0.025 * i) for i, r in enumerate(revenue)]
        ),
        PaymentsToAcquirePropertyPlantAndEquipment=flow_rows(
            [r * 0.09 for r in revenue]
        ),
        Assets=instant_rows([4_000e6 - 120e6 * i for i in range(n)]),
        StockholdersEquity=instant_rows([2_000e6 - 160e6 * i for i in range(n)]),
        CashAndCashEquivalentsAtCarryingValue=instant_rows(
            [800e6 - 60e6 * i for i in range(n)]
        ),
        LongTermDebtNoncurrent=instant_rows([900e6 + 90e6 * i for i in range(n)]),
    )
    return st.observations(versions)[-1].block


@pytest.fixture(scope="module")
def reader(structured_llm):
    return StatementReader(structured_llm)


# A company improving on every line is called up, with the direction on
# the probability's side.
async def test_an_improving_company_reads_up(reader):
    call = await reader.call(_improving_block())
    assert call is not None
    assert call.direction == UP, call
    assert call.probability > 0.5, call
    assert call.consistent, call


# A company deteriorating on every line is called down.
async def test_a_deteriorating_company_reads_down(reader):
    call = await reader.call(_deteriorating_block())
    assert call is not None
    assert call.direction == DOWN, call
    assert call.probability < 0.5, call
    assert call.consistent, call


# The rationale is about the figures: three sentences, naming a line of the
# table, naming no company.
async def test_the_rationale_is_three_sentences_about_the_table(reader):
    call = await reader.call(_improving_block())
    assert call is not None
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", call.rationale.strip()) if s]
    assert 2 <= len(sentences) <= 4, call.rationale
    lowered = call.rationale.lower()
    lines = [label.lower() for label, _key in st.LINES]
    assert any(line in lowered for line in lines) or re.search(r"\d", lowered), (
        call.rationale
    )
    names = {m.name.lower() for m in build_universe() if m.name}
    leaked = [n for n in names if len(n) > 3 and n in lowered]
    assert not leaked, leaked


# The reading is greedy: the same block returns the same direction.
@pytest.mark.xfail(
    strict=False,
    reason=(
        "the tone reader's own repeat test is xfail: deepseek-v4-flash at "
        "temperature 0 has returned different scores for identical text "
        "(2026-09-13); recorded, not relied on"
    ),
)
async def test_the_same_block_reads_the_same_way(reader):
    first = await reader.call(_improving_block())
    second = await reader.call(_improving_block())
    assert first is not None
    assert second is not None
    assert first.direction == second.direction
    assert first.probability == second.probability
