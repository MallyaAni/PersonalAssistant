"""The point-in-time membership file is rebuilt from dated sources and reads back.

Synthetic change tables pin the reconstruction (re-entry, same-day renames,
changes after the snapshot, exits the table never closes); the committed
file is then checked against `universe.as_of` on dates whose answer is known
from public record.
"""

from datetime import date

import pytest

from backend.cli import market_membership as mm
from backend.market import membership, universe

D = date


# Members at the snapshot walk back through removals and additions, and
# forward from the window start, giving one interval per stint.
def test_index_intervals_reconstruct_stints():
    changes = [
        mm.Change(D(2024, 1, 10), "NEW", "OLD"),  # after the snapshot
        mm.Change(D(2022, 6, 1), "BACK", ""),  # re-entry
        mm.Change(D(2019, 3, 1), "", "BACK"),  # first exit
        mm.Change(D(2018, 5, 1), "KEEP", "KEEP"),  # same-day rename row
        mm.Change(D(2017, 1, 1), "LATE", "GONE"),
    ]
    current = frozenset({"KEEP", "BACK", "LATE", "OLD"})
    intervals, notes = mm.index_intervals(
        current, changes, snapshot=D(2023, 12, 31), start=D(2016, 1, 4)
    )
    assert intervals["BACK"] == [(D(2016, 1, 4), D(2019, 3, 1)), (D(2022, 6, 1), None)]
    assert intervals["KEEP"] == [(D(2016, 1, 4), None)]
    assert intervals["LATE"] == [(D(2017, 1, 1), None)]
    assert intervals["GONE"] == [(D(2016, 1, 4), D(2017, 1, 1))]
    assert intervals["OLD"] == [(D(2016, 1, 4), D(2024, 1, 10))]
    assert intervals["NEW"] == [(D(2024, 1, 10), None)]
    assert notes == []


# A ticker the table adds but never removes, that is not in the index
# today, is a rename the table missed: it is dropped and reported, never
# left open.
def test_index_intervals_drop_unclosed_renames():
    changes = [mm.Change(D(2018, 6, 20), "FLT", "TWX")]
    intervals, notes = mm.index_intervals(
        frozenset({"CPAY"}), changes, snapshot=D(2026, 9, 5), start=D(2016, 1, 4)
    )
    assert "FLT" not in intervals
    assert intervals["TWX"] == [(D(2016, 1, 4), D(2018, 6, 20))]
    assert any("FLT" in n and "dropped" in n for n in notes)


# The book keeps index members in its sub-industries, classifies a closed
# interval only from the curated table (a reused ticker is not the same
# company), and dates overlay names by their commit.
def test_build_records_filters_to_the_book_and_dates_the_overlay():
    constituents = [
        universe.UniverseMember("NVDA", universe.MEMBER, sub_industry="Semiconductors"),
        universe.UniverseMember("Q", universe.MEMBER, sub_industry="Semiconductor Materials & Equipment"),
        universe.UniverseMember("KO", universe.MEMBER, sub_industry="Soft Drinks & Non-alcoholic Beverages"),
    ]
    changes = [
        mm.Change(D(2025, 11, 3), "Q", ""),
        mm.Change(D(2022, 2, 15), "NDSN", "XLNX"),
        mm.Change(D(2017, 11, 15), "IQV", "Q"),
        mm.Change(D(2017, 8, 29), "Q", "WFM"),
    ]
    overlay = {"CRWV": (D(2026, 9, 4), "b38c64e2"), "NVDA": (D(2026, 9, 4), "b38c64e2")}
    records, notes = mm.build_records(constituents, changes, overlay)
    by = {}
    for r in records:
        by.setdefault(r.ticker, []).append(r)
    assert [(r.entered, r.exited) for r in by["NVDA"]] == [(mm.WINDOW_START, None)]
    assert "S&P 500 member in Semiconductors" in by["NVDA"][0].rule
    assert [(r.entered, r.exited) for r in by["XLNX"]] == [(mm.WINDOW_START, D(2022, 2, 15))]
    # Qnity is in the book from 2025; the 2017 QuintilesIMS stint under the
    # same ticker is not (no curated sub-industry), and is reported.
    assert [(r.entered, r.exited) for r in by["Q"]] == [(D(2025, 11, 3), None)]
    assert any("Q@2017-11-15" in n for n in notes)
    assert [(r.entered, r.exited) for r in by["CRWV"]] == [(D(2026, 9, 4), None)]
    assert "commit b38c64e2" in by["CRWV"][0].source
    assert "KO" not in by and "NDSN" not in by and "IQV" not in by
    assert all(r.entry_announced == r.entered for r in records)


# The committed file is what the builder produces from the committed
# sources, so a stale file cannot outlive a source change.
def test_committed_file_matches_the_rebuild():
    records, _ = mm.build_records()
    assert mm.OUTPUT_PATH.exists(), "run python -m backend.cli.market_membership"
    assert mm.OUTPUT_PATH.read_text(encoding="utf-8") == mm.render(records)


# universe.as_of now answers, and its answers on dated sessions match the
# public record: today's book is covered in full; in 2020 the overlay
# names did not exist for the desk and the acquired names were still there.
def test_as_of_reads_the_history():
    today = set(universe.book_sides(universe.build_universe()))
    assert today <= universe.as_of(D(2026, 9, 26))
    then = universe.as_of(D(2020, 6, 1))
    assert {"NVDA", "MSFT", "XLNX", "MXIM", "CTXS", "RHT", "JNPR", "QRVO"} - then == {"RHT"}
    assert not ({"CRWV", "DELL", "SMCI", "SNDK", "ALAB", "CRDO", "PLTR", "CRWD"} & then)
    assert "RHT" in universe.as_of(D(2019, 7, 12)) and "RHT" not in universe.as_of(D(2019, 7, 15))
    assert "FSLR" not in universe.as_of(D(2018, 1, 2)) and "FSLR" in universe.as_of(D(2023, 1, 3))
    # Announced-on-effective-date is the conservative convention.
    for row in membership.load_history(mm.OUTPUT_PATH):
        assert row.entry_announced == row.entered
        assert row.exit_announced == row.exited
    with pytest.raises(FileNotFoundError):
        universe.as_of(D(2020, 1, 1), history_path=mm.OUTPUT_PATH.with_name("missing.csv"))


# The universe file (`--universe`) drops the sub-industry filter and keeps
# everything else: a non-book constituent is dated from its index entry, a
# reused ticker's earlier company is still out, an exit after the snapshot
# is classified by the constituent file (the same company), and the book
# file's index intervals are a subset of the universe file's.
def test_build_records_universe_wide_keeps_every_index_member():
    constituents = [
        universe.UniverseMember("NVDA", universe.MEMBER, sub_industry="Semiconductors"),
        universe.UniverseMember("Q", universe.MEMBER, sub_industry="Semiconductor Materials & Equipment"),
        universe.UniverseMember("KO", universe.MEMBER, sub_industry="Soft Drinks & Non-alcoholic Beverages"),
        universe.UniverseMember("TTD", universe.MEMBER, sub_industry="Advertising"),
    ]
    changes = [
        mm.Change(D(2026, 9, 21), "NEWCO", "TTD"),  # after the snapshot
        mm.Change(D(2025, 11, 3), "Q", ""),
        mm.Change(D(2022, 2, 15), "NDSN", "XLNX"),
        mm.Change(D(2017, 11, 15), "IQV", "Q"),
        mm.Change(D(2017, 8, 29), "Q", "WFM"),
    ]
    overlay = {"CRWV": (D(2026, 9, 4), "b38c64e2"), "NVDA": (D(2026, 9, 4), "b38c64e2")}
    records, notes = mm.build_records(constituents, changes, overlay, universe_wide=True)
    by = {}
    for r in records:
        by.setdefault(r.ticker, []).append(r)
    assert [(r.entered, r.exited) for r in by["KO"]] == [(mm.WINDOW_START, None)]
    assert "Soft Drinks" in by["KO"][0].rule
    assert [(r.entered, r.exited) for r in by["TTD"]] == [(mm.WINDOW_START, D(2026, 9, 21))]
    assert "Advertising" in by["TTD"][0].rule
    assert [(r.entered, r.exited) for r in by["Q"]] == [(D(2025, 11, 3), None)]
    assert any("Q@2017-11-15" in n for n in notes)
    # NDSN entered by the table and is in the index today; IQV too. NEWCO
    # was added after the snapshot and is a member today by the table.
    assert [(r.entered, r.exited) for r in by["NDSN"]] == [(D(2022, 2, 15), None)]
    assert [(r.entered, r.exited) for r in by["NEWCO"]] == [(D(2026, 9, 21), None)]
    assert [(r.entered, r.exited) for r in by["CRWV"]] == [(D(2026, 9, 4), None)]
    book, _ = mm.build_records(constituents, changes, overlay)
    book_index = {(r.ticker, r.entered, r.exited) for r in book if "OVERLAY" not in r.source}
    universe_index = {(r.ticker, r.entered, r.exited) for r in records if "OVERLAY" not in r.source}
    assert book_index <= universe_index
    assert all(r.entry_announced == r.entered for r in records)


# The committed universe file is what the builder produces, like the book's.
def test_committed_universe_file_matches_the_rebuild():
    records, _ = mm.build_records(universe_wide=True)
    assert mm.UNIVERSE_OUTPUT_PATH.exists(), "run python -m backend.cli.market_membership --universe"
    assert mm.UNIVERSE_OUTPUT_PATH.read_text(encoding="utf-8") == mm.render(records)
    listed = {r.ticker for r in records}
    today = universe.tickers_with_role(universe.build_universe(), universe.FOCUS, universe.MEMBER)
    assert set(today) <= listed


# The CLI's --universe writes the universe file and --check compares it.
def test_cli_universe_writes_and_checks(tmp_path, capsys):
    target = tmp_path / "membership_history_sp500.csv"
    assert mm.main(["--universe", "--output", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == mm.UNIVERSE_OUTPUT_PATH.read_text(encoding="utf-8")
    assert mm.main(["--universe", "--check", "--output", str(target)]) == 0
    assert "today's universe" in capsys.readouterr().out
