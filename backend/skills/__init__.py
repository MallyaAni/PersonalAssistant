"""Skills: named routines the model invokes by meaning.

A skill is an instruction pack - "morning brief: the weather for Arlington,
then my scheduled tasks, then one thing to look forward to" - that a person
taught in conversation (a row in `user_skills`) or that ships with the
repository (a markdown file under `skills/`). Each is offered to the router
as its own tool, so "do my morning brief", "morning brief please", or just
"brief me" reach it by meaning rather than by matching a name. Invoking one
runs its instruction as the turn, with the ordinary tools available to it.
"""

from .packs import SkillPack, load_packs
from .repository import SkillRepository, slugify
from .tools import SKILL_PREFIX, parse_skill_call, skill_tool_definitions

__all__ = [
    "SKILL_PREFIX",
    "SkillPack",
    "SkillRepository",
    "load_packs",
    "parse_skill_call",
    "skill_tool_definitions",
    "slugify",
]
