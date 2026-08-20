"""Labelled turns for measuring which built-in action the router picks.

Every routing test that existed before this asked a binary question about one
tool in isolation - did `search_web` fire, did `edit_image` fire - over a set
chosen for that tool. Those prove a floor and cannot say what a wrong turn
became, which is the part that decides the fix. Two failures found by hand this
session read identically as "accuracy dropped": a schedule change scattering
across `search_web`, `edit_image` and `generate_image` on wording that differed
only by the time of day, and a labelled architecture diagram going to
`generate_image` every single time. The first is a small model with no right
answer available; the second was one word in the prompt. Only the second is
fixable by writing, and only a breakdown by chosen tool tells them apart.

The set is therefore weighted toward the confusable pairs rather than the easy
middle of each tool, and every case carries the tool that should have been
chosen - including `None`, which is a real answer and the commonest one.

Cost is not symmetric, and the matrix exists partly to make that visible: a
stray `search_web` costs a second, a stray `edit_image` mutates an artifact and
spends a ninety-second generation, a diagram sent to `generate_image` returns a
diffusion model's imitation of writing, and a search that should have fired and
did not returns a confident wrong answer with nothing to signal it.
"""

from dataclasses import dataclass

# The names `MainActionSelector` offers. `None` means answer directly, which is
# a decision rather than an absence of one.
SEARCH = "search_web"
GENERATE_IMAGE = "generate_image"
EDIT_IMAGE = "edit_image"
CREATE_DIAGRAM = "create_diagram"
DELEGATE_PRESENTATION = "delegate_to_presentation_agent"
NO_TOOL = "none"

TOOL_NAMES: tuple[str, ...] = (
    SEARCH,
    GENERATE_IMAGE,
    EDIT_IMAGE,
    CREATE_DIAGRAM,
    DELEGATE_PRESENTATION,
    NO_TOOL,
)


@dataclass(frozen=True, slots=True)
class SelectionCase:
    """One labelled turn and the tool that should have been chosen for it."""

    query: str
    expected: str
    # Grouping for reporting, so a regression traces to a shape of request
    # rather than only to an aggregate percentage.
    category: str
    # Whether an image is in view for this turn. `edit_image` is offered every
    # turn regardless, so this is the interface state the application checks
    # afterwards, not a gate on the decision.
    active_image: bool = False
    # Prior turns, for the cases whose meaning depends on them.
    history: tuple[tuple[str, str], ...] = ()


_OUTFIT_HISTORY = (
    (
        "do you like my style?",
        "You're wearing a black cowboy hat, a dark bomber jacket and a white t-shirt.",
    ),
    ("can you edit this to a straw hat?", "Here's the edited image."),
)
_SCOUT_HISTORY = (
    (
        "what agents do i have scheduled?",
        "Scout runs daily at 22:40. 0 feeds, 2 interests, 1 subscriber.",
    ),
)
_EMAIL_DETAILS_HISTORY = (
    (
        "Can you draft me an email to my retail team to ask for shift coverage?",
        "What shifts do you need covered, and how many people are needed?",
    ),
)
_EMAIL_DRAFT_HISTORY = (
    *_EMAIL_DETAILS_HISTORY,
    (
        "This Saturday, 8am to 7pm. Just one person.",
        "Here is the draft. Would you like a more casual or formal tone?",
    ),
)

SELECTION_CASES: tuple[SelectionCase, ...] = (
    # --- genuinely needs the web ------------------------------------------
    SelectionCase("who is the prime minister of Canada", SEARCH, "role_holder"),
    SelectionCase("what's the weather in Raleigh today", SEARCH, "live_data"),
    SelectionCase("how much does a Tesla Model 3 cost now", SEARCH, "live_data"),
    SelectionCase("what happened in the Nvidia earnings call", SEARCH, "news"),
    # --- a brand-new picture ----------------------------------------------
    SelectionCase("draw me a picture of a red bicycle", GENERATE_IMAGE, "picture"),
    SelectionCase(
        "create an image of a sunset over mountains", GENERATE_IMAGE, "picture"
    ),
    SelectionCase(
        "generate an image of a cozy cabin in the snow", GENERATE_IMAGE, "picture"
    ),
    # --- the artifact asked for decides, not the subject -------------------
    #
    # These three were labelled the other way on 2026-08-17, after an
    # architecture request produced an unreadable picture. Relabelled on
    # 2026-08-19 by the owner's judgement: "image generally refers to picture.
    # it didnt say architecture diagram or diagram". A technical subject does
    # not turn a request for a picture into a request for a chart, and the user
    # who wants a diagram has a plain word for it.
    #
    # The cost of each mistake is not symmetric, which is why this is a
    # judgement rather than an obvious call: a picture of an architecture has
    # labels a diffusion model can only imitate, while a diagram offered where
    # a picture was wanted is recovered by asking again. The owner has chosen
    # to pay the first cost.
    SelectionCase(
        "create an image that describes medallion architecture in databricks, "
        "using a whiteboard",
        GENERATE_IMAGE,
        "picture_of_a_technical_subject",
    ),
    SelectionCase(
        "create an image of our data pipeline on a whiteboard",
        GENERATE_IMAGE,
        "picture_of_a_technical_subject",
    ),
    SelectionCase(
        "show me a picture of how our services connect",
        GENERATE_IMAGE,
        "picture_of_a_technical_subject",
    ),
    # The other direction still has to hold: naming the artifact is what
    # chooses it, so these stay diagrams.
    SelectionCase("draw a diagram of our data pipeline", CREATE_DIAGRAM, "diagram"),
    SelectionCase(
        "create an architecture diagram for the payments service",
        CREATE_DIAGRAM,
        "diagram",
    ),
    SelectionCase("draw a flowchart of the deploy pipeline", CREATE_DIAGRAM, "diagram"),
    SelectionCase(
        "make a sequence diagram of the login flow", CREATE_DIAGRAM, "diagram"
    ),
    # --- editing the picture in view ---------------------------------------
    SelectionCase(
        "make it black and white",
        EDIT_IMAGE,
        "edit",
        active_image=True,
        history=_OUTFIT_HISTORY,
    ),
    SelectionCase(
        "remove the hat from this picture",
        EDIT_IMAGE,
        "edit",
        active_image=True,
        history=_OUTFIT_HISTORY,
    ),
    SelectionCase(
        "can you make the jacket blue",
        EDIT_IMAGE,
        "edit",
        active_image=True,
        history=_OUTFIT_HISTORY,
    ),
    # --- a question about the picture is not an instruction ----------------
    SelectionCase(
        "which hat do you like better for this outfit?",
        NO_TOOL,
        "opinion_about_image",
        active_image=True,
        history=_OUTFIT_HISTORY,
    ),
    SelectionCase(
        "do you recommend a straw hat instead?",
        NO_TOOL,
        "opinion_about_image",
        active_image=True,
        history=_OUTFIT_HISTORY,
    ),
    SelectionCase(
        "would the cowboy hat have suited me better?",
        NO_TOOL,
        "opinion_about_image",
        active_image=True,
        history=_OUTFIT_HISTORY,
    ),
    # --- "edit" about something that is not a picture ----------------------
    SelectionCase(
        "let's edit this project plan to push the deadline back a week",
        NO_TOOL,
        "edit_not_an_image",
    ),
    SelectionCase("edit my resume to remove my last job", NO_TOOL, "edit_not_an_image"),
    # --- slide decks --------------------------------------------------------
    SelectionCase(
        "put together a six-slide deck on our Q3 results",
        DELEGATE_PRESENTATION,
        "deck",
    ),
    SelectionCase(
        "I need to present the roadmap next week, build me a presentation",
        DELEGATE_PRESENTATION,
        "deck",
    ),
    # --- the user's own settings, which no tool covers ---------------------
    SelectionCase(
        "can you change the schedule to 9:25pm everyday?",
        NO_TOOL,
        "agent_config",
        history=_SCOUT_HISTORY,
    ),
    SelectionCase(
        "yes id like scout for 9:40pm", NO_TOOL, "agent_config", history=_SCOUT_HISTORY
    ),
    SelectionCase(
        "make it weekly instead", NO_TOOL, "agent_config", history=_SCOUT_HISTORY
    ),
    SelectionCase("what agents do i have scheduled?", NO_TOOL, "agent_config"),
    # --- short answers continue the writing task already in progress --------
    SelectionCase(
        "This Saturday, 8am to 7pm",
        NO_TOOL,
        "writing_followup",
        history=_EMAIL_DETAILS_HISTORY,
    ),
    SelectionCase(
        "More casual",
        NO_TOOL,
        "writing_followup",
        history=_EMAIL_DRAFT_HISTORY,
    ),
    SelectionCase(
        "Add that I can swap next weekend",
        NO_TOOL,
        "writing_followup",
        history=_EMAIL_DRAFT_HISTORY,
    ),
    SelectionCase(
        "Ask them to reply by Thursday at noon",
        NO_TOOL,
        "writing_followup",
        history=_EMAIL_DRAFT_HISTORY,
    ),
    # --- writing about a visual subject is still writing --------------------
    SelectionCase("write me a haiku about rain", NO_TOOL, "creative_writing"),
    SelectionCase(
        "write a short story about a mountain at sunset", NO_TOOL, "creative_writing"
    ),
    # --- ordinary conversation and the user's own memory --------------------
    SelectionCase("what is my name?", NO_TOOL, "personal_memory"),
    SelectionCase("remind me what my interests are", NO_TOOL, "personal_memory"),
    SelectionCase("what is the derivative of x squared", NO_TOOL, "stable_knowledge"),
    SelectionCase(
        "explain the difference between TCP and UDP", NO_TOOL, "stable_knowledge"
    ),
)

# Set from the measured baseline once, deliberately low enough to catch a
# collapse rather than referee a close call. The pairs this set is weighted
# toward are exactly the ones a 4B router is unstable on, so a floor near the
# measured value would fail honest runs about as often as dishonest ones - the
# same trap `backend/vision/grounding_cases.py` records. Compare two models
# with the CLI, which reports the matrix; use this only as a gate.
ACCURACY_FLOOR = 0.70

# Preserve each built-in capability independently so a strong common class
# cannot hide the collapse of a smaller, expensive one. These sit below the
# measured current baseline, including the known 0.80 diagram result.
PER_TOOL_ACCURACY_FLOORS: dict[str, float] = {
    SEARCH: 0.75,
    GENERATE_IMAGE: 0.75,
    EDIT_IMAGE: 0.66,
    CREATE_DIAGRAM: 0.60,
    DELEGATE_PRESENTATION: 0.50,
    NO_TOOL: 0.85,
}
