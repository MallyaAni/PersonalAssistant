"""The What's on pack ships and says what it is for."""

from backend.skills.packs import load_packs


def test_the_whats_on_pack_loads_with_its_format() -> None:
    # The slug comes from the name ("What's on" -> what-s-on), not the file name.
    pack = load_packs()["what-s-on"]
    assert pack.name == "What's on"
    for word in ("venue", "map", "price", "YouTube", "Instagram", "already past"):
        assert word.lower() in pack.instruction.lower(), word
    # The description steers the router: it must say what the skill is for
    # (listings on given days) and what it is not for - a dinner
    # recommendation was routed to it twice (2026-08-28).
    assert "What is on somewhere on given days" in pack.description
    assert "not for recommending a place" in pack.description
