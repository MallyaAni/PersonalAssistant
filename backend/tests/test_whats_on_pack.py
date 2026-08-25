"""The What's on pack ships and says what it is for."""

from backend.skills.packs import load_packs


def test_the_whats_on_pack_loads_with_its_format() -> None:
    # The slug comes from the name ("What's on" -> what-s-on), not the file name.
    pack = load_packs()["what-s-on"]
    assert pack.name == "What's on"
    for word in ("venue", "map", "price", "YouTube", "Instagram", "already past"):
        assert word.lower() in pack.instruction.lower(), word
    assert "Events, nightlife" in pack.description
