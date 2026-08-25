"""The unprompted introduction a newly approved person receives.

This is the only message AniOS sends to someone who has not spoken to it yet,
which makes it the one message with no context to survive a mistake. If it
names a capability that does not exist, the first thing the person learns is
that the assistant is unreliable, and they learn it before they have any
history to weigh it against.

So the assertions here are about what the model actually wrote, not about
whether the call was made. Two properties matter and they pull in opposite
directions:

  It must not invent.
    A model given a list and asked to write warmly will round "search the web"
    up to "book things for you". The refusal cases below hand it a
    deliberately small capability list and check it does not reach past it.

  It must not be useless.
    A message so hedged it says nothing is a different failure with the same
    cause. Given a real list, it has to actually describe the real things.

The list is deliberately passed in rather than read from the running
deployment: this asserts the prompt's behaviour given a list, which is the
part that can regress silently. What the live list contains is the selector's
business and is tested where the selector is.
"""

import pytest

from backend.core.prompts import render

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


# The shape `_render_capability_context` produces, written out here so the test
# does not depend on the live deployment's configuration.
REAL_CAPABILITIES = (
    "- Web search: looking something up online and reading the results back.\n"
    "- Weather: the current forecast for a place.\n"
    "- Image generation: making a picture from a description.\n"
    "- Image editing: changing a picture they send.\n"
    "- Scheduled tasks: doing something later or on a repeating schedule.\n"
)
REAL_AGENTS = (
    "- Scout: anything that should happen on a schedule rather than right "
    "now - a recurring sweep for things happening nearby, and equally a "
    "recurring search or report on any subject.\n"
    "- Deck: building a slide deck from a brief.\n"
)

# A deliberately narrow deployment. Everything absent here is something the
# model must not offer, and each one is a plausible thing to hallucinate.
NARROW_CAPABILITIES = "- Web search: looking something up online.\n"
NARROW_AGENTS = ""


def _welcome(llm, name: str, agents: str, capabilities: str) -> str:
    prompt = render(
        "welcome/system",
        display_name=name,
        agents=agents,
        capabilities=capabilities,
    )
    answer = llm.chat(
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"Write the welcome message for {name} now. "
                "Return only the message.",
            },
        ],
        400,
        None,
        0.0,
    )
    return str(answer.get("content") or answer).strip()


async def test_the_welcome_describes_what_the_system_can_actually_do(llm) -> None:
    """Given the real list, it has to be genuinely informative."""
    text = _welcome(llm, "Saps", REAL_AGENTS, REAL_CAPABILITIES)
    lowered = text.lower()

    assert text, "the model returned nothing"
    # Greets the person. The name is the one piece of personalisation it has.
    assert "saps" in lowered, text

    # It need not mention every capability - the prompt asks it to choose - but
    # a message that names none of them is not an introduction to anything.
    mentioned = sum(
        any(word in lowered for word in words)
        for words in (
            ("search", "look up", "looking up", "find out"),
            ("weather", "forecast"),
            ("remind", "schedule", "recurring", "every monday", "later"),
            ("image", "picture", "photo"),
            ("slide", "deck", "presentation"),
        )
    )
    assert mentioned >= 2, f"named too few real capabilities ({mentioned}): {text}"


async def test_the_welcome_does_not_promise_what_is_absent(llm) -> None:
    """The refusal case, and the reason this file exists.

    Given a deployment that can only search, the model must not offer the
    things a welcome message wants to offer. Each phrase below is a real
    capability of some assistant, none of them are in the list, and a warm
    generic welcome reaches for all of them.
    """
    text = _welcome(llm, "Saps", NARROW_AGENTS, NARROW_CAPABILITIES)
    lowered = text.lower()

    forbidden = {
        "email": ("email", "e-mail", "inbox"),
        "calling": ("call you", "phone call", "make a call"),
        "booking": ("book a", "booking", "make a reservation", "reserve a"),
        "shopping": ("order for you", "buy it", "make a purchase"),
        "smart home": ("smart home", "lights on", "thermostat"),
        "music": ("play music", "spotify", "play a song"),
    }
    named = [
        label
        for label, phrases in forbidden.items()
        if any(phrase in lowered for phrase in phrases)
    ]
    assert not named, f"offered capabilities it does not have {named}: {text}"


async def test_the_welcome_is_a_text_message_not_a_brochure(llm) -> None:
    """Shape, because the medium is iMessage.

    A model asked for a welcome writes onboarding copy - headers, bullets, a
    numbered getting-started list. That is wrong in a text bubble, and the
    prompt says so; this checks the prompt is winning.
    """
    text = _welcome(llm, "Saps", REAL_AGENTS, REAL_CAPABILITIES)

    assert "\n- " not in text and not text.startswith("- "), (
        "wrote a bullet list: " + text
    )
    assert "#" not in text, "used markdown headers: " + text
    assert "**" not in text, "used markdown bold: " + text
    assert not any(f"\n{n}." in text for n in (1, 2, 3)), (
        "wrote a numbered list: " + text
    )

    words = len(text.split())
    # Generous either side of the prompt's 120-200. The failure being caught is
    # a wall of text or a one-liner, not a message that ran twenty words over.
    assert 40 <= words <= 150, f"{words} words is wrong for a hello by text: {text}"


async def test_the_welcome_is_addressed_to_the_person_not_about_them(llm) -> None:
    """It must be the message, not a description of the message.

    Asked to write something, models routinely answer "Here's a welcome
    message you could send:" and then the message. That preamble would be sent
    verbatim to a real person's phone.
    """
    text = _welcome(llm, "Saps", REAL_AGENTS, REAL_CAPABILITIES)
    opening = text[:120].lower()

    for tell in ("here's", "here is", "sure,", "certainly", "of course"):
        assert not opening.startswith(tell), f"answered about the message: {text}"
    assert "welcome message" not in text.lower(), (
        "described itself as a welcome message: " + text
    )


async def test_the_welcome_says_nothing_about_where_conversations_live(llm) -> None:
    """A hello is not the place to talk about data.

    The first real generation told a guest her conversations stay on "your
    own machines" (false - the owner's). A corrected sentence lasted a day;
    then the operator asked for the subject to go entirely. So: no storage,
    privacy, hardware, servers, or cloud in the welcome at all.
    """
    text = _welcome(llm, "Saps", REAL_AGENTS, REAL_CAPABILITIES)
    lowered = text.lower()
    mentioned = [
        word
        for word in ("machine", "hardware", "server", "cloud", "privacy", "private", "stored", "stays on", "stay on")
        if word in lowered
    ]
    assert not mentioned, f"talked about where data lives {mentioned}: {text}"


# The operator's verdict on the first version, 2026-08-25: "so wordy... it
# needs to be positive, light-hearted and welcoming rather than cautionary".
# A hello that reads like terms of service is the wrong first impression.
_CAUTIONARY = (
    "note that",
    "keep in mind",
    "be aware",
    "please note",
    "however",
    "unfortunately",
    "can't",
    "cannot",
    "unable",
    "not able",
    "limit",
    "just so you know",
    "warning",
    "caution",
)


async def test_the_welcome_is_a_warm_hello_not_a_cautionary_briefing(llm) -> None:
    from backend.tests.functional.semantic import states

    text = _welcome(llm, "Saps", REAL_AGENTS, REAL_CAPABILITIES)
    lowered = text.lower()
    cautionary = [phrase for phrase in _CAUTIONARY if phrase in lowered]
    assert not cautionary, f"cautionary wording {cautionary}: {text}"
    assert states(
        text,
        "The message is warm, upbeat and welcoming in tone, like a friendly "
        "hello, and contains no warnings, caveats or cautions.",
    ), text
