"""One namespace for every account this repository's harnesses create.

On 2026-08-29 the operator found ten unfamiliar profiles sitting beside their
own. They were the journey sweep's: it minted a fresh random id per run, and
any run that did not reach its cleanup - a killed `timeout`, a crash, the
deploy's single-journey retry, which opened an account of its own - left one
behind permanently. Nothing in the system could tell those apart from a
person's account except by recognising a prefix, and the recognising was done
by a list of prefixes kept somewhere else, which is a list that goes stale the
first time someone writes a new harness.

So identity is derived here and nowhere else. A harness asks for an id; a
cleaner asks whether an id is one. Add a harness tomorrow and it is covered by
construction, because there is no second place to remember to update.

The namespace is a prefix on the account id rather than a column, matching how
group rooms already identify themselves (`backend/groups/repository.py`). That
means the guarantee is only as strong as the prefix being unusable by a
person - so account creation refuses it (`backend/services/auth_service.py`),
and every destructive tool that acts on it checks a second, behavioural
property as well: a harness account never has a consented delivery address.
"""

from __future__ import annotations

import re

# The prefix no person's account may carry.
HARNESS_PREFIX = "harness_"

# Ids from before this namespace existed. Historical and closed: it describes
# accounts that were created in the past, so it never needs another entry, and
# a new harness must not add one - it calls `harness_id` instead.
LEGACY_PREFIXES = ("sweep_", "sweepm_", "search_e2e_", "image_e2e_")

_UNSAFE = re.compile(r"[^a-z0-9]+")


# The account id for one harness role, e.g. harness_journeys, and optionally
# for one isolated run of it.
#
# `run` exists for the edge case a single fixed id cannot serve: two sweeps
# against the same database at once, where each would otherwise purge the
# other's account mid-flight. Left empty - which is the normal case, and what
# the operator asked for - every run shares one account, so a leak is bounded
# at one stale row per role rather than one per run.
def harness_id(role: str, run: str = "") -> str:
    parts = [_slug(role)] + ([_slug(run)] if _slug(run) else [])
    return HARNESS_PREFIX + "_".join(part for part in parts if part)


# Whether an id belongs to a harness - the current namespace or the closed set
# of shapes that predate it.
def is_harness_id(user_id: str) -> bool:
    value = str(user_id or "")
    return value.startswith(HARNESS_PREFIX) or value.startswith(LEGACY_PREFIXES)


def _slug(value: str) -> str:
    return _UNSAFE.sub("_", str(value or "").strip().casefold()).strip("_")
