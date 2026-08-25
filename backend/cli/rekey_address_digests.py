"""Re-digest every stored phone and address under the keyed HMAC.

The unkeyed SHA-256 these columns carried was exhaustible offline over the
phone-number keyspace (the SECURITY.md C12 gap). The code now writes keyed
digests; this backfill moves every existing row onto the same key so lookups
keep matching. Idempotent: a row whose digest already matches is left alone,
so re-running after a partial failure - or after a key rotation, or after
restoring an older dump - is the recovery path, not a special case.

Run inside a container that holds the real key:
    docker compose exec backend python -m backend.cli.rekey_address_digests
"""

import argparse
import asyncio
import json

from sqlalchemy import select

from backend.core.phone import matching_key
from backend.database.session import AsyncSessionLocal
from backend.discovery.addressing import address_digest, normalize_address
from backend.models.auth import AccessRequest
from backend.models.discovery_subscriber import DiscoverySubscriber


# One pass over both tables in one transaction: the two digests must match for
# the allowlist to work, so a half-rekeyed state is exactly the silent failure
# this must never leave behind. The sealed plaintext is the source of truth
# and the digest is always recomputable from it, which is what makes the pass
# safe to repeat.
async def rekey(dry_run: bool = False) -> dict[str, int]:
    changed = {"access_requests": 0, "discovery_subscribers": 0, "skipped": 0}
    async with AsyncSessionLocal() as session:
        requests = (
            (
                await session.execute(
                    select(AccessRequest).where(AccessRequest.phone.is_not(None))
                )
            )
            .scalars()
            .all()
        )
        for row in requests:
            try:
                fresh = address_digest(matching_key(row.phone))
            except Exception:
                # A stored number that no longer parses cannot be looked up
                # under either scheme; leave it for a human rather than
                # inventing a digest for it.
                changed["skipped"] += 1
                continue
            if row.phone_digest != fresh:
                row.phone_digest = fresh
                changed["access_requests"] += 1
        subscribers = (
            (await session.execute(select(DiscoverySubscriber))).scalars().all()
        )
        for row in subscribers:
            fresh = address_digest(normalize_address((row.address or "").strip()))
            if row.address_digest != fresh:
                row.address_digest = fresh
                changed["discovery_subscribers"] += 1
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return changed


# Entry point; prints what changed so the operator can see the rekey landed.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing anything",
    )
    arguments = parser.parse_args(argv)
    changed = asyncio.run(rekey(dry_run=arguments.dry_run))
    print(json.dumps(changed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
