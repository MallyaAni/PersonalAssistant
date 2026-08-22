"""Skills shipped with the repository, read from `skills/*.md`.

One file per skill: a short front matter with `name` and `description`,
then the instruction as the body. The description is what the router sees
when deciding whether a message invokes it; the body is what runs. Packs
are offered to every user; a user-taught skill with the same slug wins.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .repository import slugify

logger = logging.getLogger(__name__)

_PACKS_DIR = Path(__file__).resolve().parents[2] / "skills"


@dataclass(frozen=True, slots=True)
class SkillPack:
    slug: str
    name: str
    description: str
    instruction: str

    # The same shape a user skill row takes, so one list serves the router.
    def as_skill(self) -> dict[str, str]:
        return {
            "id": f"pack:{self.slug}",
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "instruction": self.instruction,
            "source": "pack",
        }


# Every well-formed pack on disk, by slug. Cached: the folder is part of the
# deployed image and does not change while the process runs.
@lru_cache(maxsize=1)
def load_packs(directory: Path | None = None) -> dict[str, SkillPack]:
    folder = directory or _PACKS_DIR
    packs: dict[str, SkillPack] = {}
    if not folder.is_dir():
        return packs
    for path in sorted(folder.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        pack = _parse(path)
        if pack is not None:
            packs[pack.slug] = pack
    return packs


# One file as a pack, or None with a warning when it is missing its name
# or body - a half-written pack must not be offered as a tool.
def _parse(path: Path) -> SkillPack | None:
    text = path.read_text(encoding="utf-8")
    front: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].splitlines():
                key, sep, value = line.partition(":")
                if sep:
                    front[key.strip().lower()] = value.strip()
            body = parts[2]
    name = front.get("name") or path.stem.replace("-", " ")
    instruction = body.strip()
    if not instruction:
        logger.warning("skill_pack_empty", extra={"path": str(path)})
        return None
    return SkillPack(
        slug=slugify(name),
        name=name,
        description=front.get("description") or instruction[:200],
        instruction=instruction,
    )
