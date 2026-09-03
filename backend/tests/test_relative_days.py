"""A memory's "today" is written as the date it meant, so it stays true."""
from datetime import UTC, datetime

from backend.core.relative_days import absolutize_days, has_relative_day

WED = datetime(2026, 9, 2, 9, 22, tzinfo=UTC)


def test_today_tomorrow_tonight_and_yesterday_become_dates():
    assert absolutize_days("Ani and Jenos are going to trivia at Courthouse Social today; they go often.", WED) == (
        "Ani and Jenos are going to trivia at Courthouse Social on Wednesday 2 September 2026; they go often."
    )
    assert absolutize_days("dentist tomorrow at 9", WED) == "dentist on Thursday 3 September 2026 at 9"
    assert absolutize_days("salsa tonight", WED) == "salsa on the evening of Wednesday 2 September 2026"
    assert absolutize_days("we saw a play yesterday", WED) == "we saw a play on Tuesday 1 September 2026"
    assert absolutize_days("flying out on today", WED) == "flying out on Wednesday 2 September 2026"


def test_this_weekend_is_the_coming_saturday_and_sunday():
    assert absolutize_days("beach this weekend", WED) == "beach the weekend of 5-6 September 2026"


def test_text_without_relative_words_is_untouched():
    text = "Jen drives a red Mini Cooper"
    assert absolutize_days(text, WED) == text
    assert not has_relative_day(text) and has_relative_day("trivia today")
