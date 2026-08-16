"""Labelled image questions for measuring the visual-search decision.

An uploaded picture reaches two models that can both be confidently wrong about
what is in it: a small vision model with little product knowledge, and a main
model whose knowledge is dated. `VisualSearchGrounding` exists so identification
is grounded in a real search instead of recalled. Whether it *decides* to search
had never been measured, and the first measurement found it skipping searches it
should make -- answering "what model of shoe is this?" from memory every time.

The label is deliberately not "is this question about an object". It is: **would
being out of date or mistaken about a real-world fact make this answer wrong?**
A question about a plant's watering schedule needs the plant identified; a
question about how many apples are in a bowl does not, however photographic the
subject. Each case therefore pairs an observation with a question, because the
same picture can need a search or not depending on what was asked of it.

Skipping a needed search is the expensive error and the invisible one: the user
gets a fluent, specific, wrong answer with nothing to suggest it was guessed. A
needless search costs a second. The floors below are set accordingly.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GroundingCase:
    """One labelled image question and whether answering it needs the web."""

    # What the vision model reported seeing, as the decision actually receives it.
    observation: str
    question: str
    needs_search: bool
    # Grouping for reporting, so a regression traces to a shape of question
    # rather than only to an aggregate percentage.
    category: str


GROUNDING_CASES: tuple[GroundingCase, ...] = (
    # --- identification: the answer is a real-world fact to look up ---------
    GroundingCase(
        observation=(
            "A small champagne-gold desktop computer with a dense perforated "
            "metal front panel, roughly the footprint of a paperback book. No "
            "legible branding or model text is visible on the chassis."
        ),
        question="What is this device?",
        needs_search=True,
        category="identify_device",
    ),
    GroundingCase(
        observation=(
            "A blue running shoe photographed on a wooden floor. The tongue "
            "carries small white lettering that is only partly legible."
        ),
        question="What model of shoe is this?",
        needs_search=True,
        category="identify_product",
    ),
    GroundingCase(
        observation=(
            "A circuit board with a large square black chip at its centre, "
            "surrounded by smaller components and a row of gold contacts along "
            "one edge."
        ),
        question="What board is this and what is it used for?",
        needs_search=True,
        category="identify_device",
    ),
    GroundingCase(
        observation=(
            "A dark green sports car with a low bonnet, four round tail lights "
            "and a rear spoiler, parked on a gravel drive."
        ),
        question="What car is this?",
        needs_search=True,
        category="identify_product",
    ),
    GroundingCase(
        observation=(
            "A potted plant with thick, upright, sword-shaped leaves edged in "
            "yellow, growing in a grey ceramic pot on a windowsill."
        ),
        question="What kind of plant is this and how often should I water it?",
        needs_search=True,
        category="identify_species",
    ),
    GroundingCase(
        observation=(
            "A small brown bird with a speckled breast and a thin pointed beak, "
            "perched on a garden fence."
        ),
        question="What species is this?",
        needs_search=True,
        category="identify_species",
    ),
    GroundingCase(
        observation=(
            "A cluster of pale mushrooms with domed caps and white gills, "
            "growing at the base of a tree."
        ),
        question="Are these safe to eat?",
        needs_search=True,
        category="identify_species",
    ),
    GroundingCase(
        observation=(
            "A tall stone tower with a clock face near its top, photographed "
            "against an overcast sky, with a bridge visible to one side."
        ),
        question="Where was this taken?",
        needs_search=True,
        category="identify_place",
    ),
    GroundingCase(
        observation=(
            "A wine bottle with a cream label bearing a small crest, the word "
            "Barolo, and the year 2016."
        ),
        question="Is this a good vintage?",
        needs_search=True,
        category="identify_product",
    ),
    GroundingCase(
        observation=(
            "A snake with a diamond-patterned back coiled on a patch of dry "
            "leaves, its head raised slightly."
        ),
        question="Is this one dangerous?",
        needs_search=True,
        category="identify_species",
    ),
    GroundingCase(
        observation=(
            "A white kitchen appliance with a small digital display, a hinged "
            "lid and a control dial, sitting on a countertop."
        ),
        question="What does this appliance do?",
        needs_search=True,
        category="identify_device",
    ),
    # --- answerable from the description alone -----------------------------
    GroundingCase(
        observation=(
            "A wooden bowl on a kitchen counter holding six red apples and two "
            "green pears."
        ),
        question="How many apples are in the bowl?",
        needs_search=False,
        category="counting",
    ),
    GroundingCase(
        observation=(
            "A person wearing a straw hat, a dark bomber jacket and a white "
            "t-shirt, standing by the water at sunset."
        ),
        question="Do you think this outfit works?",
        needs_search=False,
        category="opinion",
    ),
    GroundingCase(
        observation="A digital kitchen scale displaying the value 428 g on its LCD.",
        question="What weight is shown on the scale?",
        needs_search=False,
        category="reading_value",
    ),
    GroundingCase(
        observation=(
            "A living room with a grey sofa against the far wall, a floor lamp "
            "to its left and a low wooden table in front of it."
        ),
        question="Which side of the sofa is the lamp on?",
        needs_search=False,
        category="spatial",
    ),
    GroundingCase(
        observation=(
            "A whiteboard covered in handwriting. The legible text reads "
            "'standup 9:15' and 'retro Thursday 3pm'."
        ),
        question="What time is the retro?",
        needs_search=False,
        category="reading_value",
    ),
    GroundingCase(
        observation=(
            "A photograph of a beach at dusk, the sky graded from orange near "
            "the horizon to deep blue overhead, with two figures silhouetted "
            "at the water's edge."
        ),
        question="What's the mood of this photo?",
        needs_search=False,
        category="opinion",
    ),
    GroundingCase(
        observation=(
            "A desk with an open laptop, a closed notebook, a mug and a pair of "
            "headphones, with cables running across the surface."
        ),
        question="Does this desk look tidy to you?",
        needs_search=False,
        category="opinion",
    ),
    GroundingCase(
        observation=(
            "A group photograph of five people standing in a row in front of a "
            "brick wall, all facing the camera."
        ),
        question="How many people are in this picture?",
        needs_search=False,
        category="counting",
    ),
    GroundingCase(
        observation=(
            "A bar chart with four bars labelled Q1 through Q4, of heights 12, "
            "19, 15 and 24 on the vertical axis."
        ),
        question="Which quarter was highest and by how much?",
        needs_search=False,
        category="reading_value",
    ),
    GroundingCase(
        observation=(
            "Two mugs side by side on a table, the left one matte black and the "
            "right one glossy cream."
        ),
        question="Which of these two would you pick for a gift?",
        needs_search=False,
        category="opinion",
    ),
)

# Missing a needed search is the invisible failure -- a fluent, specific, wrong
# answer about the user's own photograph -- while a needless search costs about
# a second. Recall is therefore the number that matters, and specificity is held
# only high enough to catch a decision that has started searching everything.
#
# Set from measurement, and set to catch collapse rather than to referee a
# close call. Measured against the real routing model: the pre-revision prompt
# scored recall 0.7727 (51/66); the identify-then-judge revision scored 0.8636
# twice independently, at 66 and 88 positive samples, specificity 0.95-0.98.
#
# Those two prompts are nine points apart, which a 20-40 sample run cannot
# separate from noise - a floor at 0.80 flaked roughly one run in six against a
# true rate of 0.8636, and a floor high enough to fail the old prompt reliably
# would fail the new one nearly as often. So the floors sit low enough to be a
# stable gate against a real regression, and comparing two prompts is the job of
# `python -m backend.cli.evaluate_visual_grounding`, which scores both at a
# repetition count that can actually tell them apart. Do not raise these to make
# the gate "stricter": that trades a signal for a coin flip.
RECALL_FLOOR = 0.70
SPECIFICITY_FLOOR = 0.80
