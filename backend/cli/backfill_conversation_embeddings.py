"""Embed the turns that were stored before turns were embedded.

Recall searches `conversations.embedding`, and every turn written before that
column existed has none. A NULL is skipped by the search rather than matching
everything, so the effect is not a wrong answer - it is a user whose history
simply stops at the day this shipped. This walks the backlog once.

Re-runnable and additive: it only touches rows with no vector, commits in
batches so an interrupted run keeps its progress, and never rewrites a turn's
text. The development database holds real conversations and has no backups.
"""

import argparse
import asyncio
import logging

from sqlalchemy import select

from backend.config.settings import settings
from backend.core.dependencies import get_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.models.conversation import Conversation

logger = logging.getLogger(__name__)


async def backfill(batch_size: int, limit: int | None, dry_run: bool) -> int:
    embeddings = get_embedding_provider()
    embedded = 0
    async with AsyncSessionLocal() as session:
        statement = (
            select(Conversation)
            .where(Conversation.embedding.is_(None))
            .order_by(Conversation.created_at)
        )
        if limit is not None:
            statement = statement.limit(limit)
        pending = (await session.execute(statement)).scalars().all()
        print(f"{len(pending)} turns without a vector")
        if dry_run:
            return 0

        for index, turn in enumerate(pending, start=1):
            # The query is what the user said, which is what recall looks for.
            # The response is the assistant's own words and would match its own
            # phrasing back rather than the user's.
            text = (turn.query or "").strip()
            if not text:
                continue
            try:
                turn.embedding = await asyncio.to_thread(embeddings.embed_query, text)
            except Exception:
                # One unembeddable turn must not end the run; it stays NULL and
                # the next run picks it up.
                logger.warning("Could not embed turn %s", turn.id, exc_info=True)
                continue
            turn.embedding_model = settings.EMBEDDING_MODEL
            embedded += 1
            if index % batch_size == 0:
                await session.commit()
                print(f"  committed {embedded}/{len(pending)}")
        await session.commit()
    return embedded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report how many turns need a vector and change nothing",
    )
    args = parser.parse_args(argv)
    embedded = asyncio.run(backfill(args.batch_size, args.limit, args.dry_run))
    print(f"embedded {embedded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
