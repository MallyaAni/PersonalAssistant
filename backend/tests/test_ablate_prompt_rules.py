"""The ablation tool splits the prompt into sentences and removes exactly one."""

from backend.cli.ablate_prompt_rules import sentences, without


def test_sentences_split_on_ends_and_keep_paragraphs():
    text = "First rule here. Second rule follows! Third?\n\nA new paragraph. Its second sentence."
    parts = sentences(text)
    assert parts == ["First rule here.", "Second rule follows!", "Third?", "A new paragraph.", "Its second sentence."]


def test_without_removes_one_sentence_only():
    text = "Keep this. Drop this. Keep this."
    assert without(text, "Drop this.") == "Keep this.  Keep this."
    assert without(text, "Keep this.").count("Keep this.") == 1
