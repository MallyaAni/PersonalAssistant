"""Re-embed every turn whose vector is not from the current space.

Recall searches `conversations.embedding`, and a vector is only comparable
within one space - one embedding model AND one content scheme. Rows record the
signature they were built with (`backend/memory/turn_embedding.py`); retrieval
matches only the current signature, so any row built under an old model, an
old scheme, or never embedded at all is invisible until this walks it. That
makes this one idempotent command the whole migration story for either kind of
change: flip the model or bump the scheme, run this, done.

Re-runnable and additive: it targets only rows whose signature does not match,
commits in batches so an interrupted run keeps its progress, and never
rewrites a turn's text. The development database holds real conversations and
has no second copy beyond the nightly dumps.
"""

import argparse
import asyncio
import logging

from sqlalchemy import or_, select

from backend.core.dependencies import get_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.memory.turn_embedding import turn_embedding_signature, turn_embedding_text
from backend.models.conversation import Conversation

logger = logging.getLogger(__name__)


# Embed both voices of every out-of-signature turn, oldest first.
async def backfill(batch_size: int, limit: int | None, dry_run: bool) -> int:
    embeddings = get_embedding_provider()
    signature = turn_embedding_signature()
    embedded = 0
    async with AsyncSessionLocal() as session:
        statement = (
            select(Conversation)
            .where(
                or_(
                    Conversation.embedding.is_(None),
                    Conversation.embedding_model.is_distinct_from(signature),
                )
            )
            .order_by(Conversation.created_at)
        )
        if limit is not None:
            statement = statement.limit(limit)
        pending = (await session.execute(statement)).scalars().all()
        print(f"{len(pending)} turns outside the current space ({signature})")
        if dry_run:
            return 0

        for index, turn in enumerate(pending, start=1):
            text = turn_embedding_text(turn.query or "", turn.response or "")
            if not text:
                continue
            try:
                turn.embedding = await asyncio.to_thread(embeddings.embed_query, text)
            except Exception:
                # One unembeddable turn must not end the run; it keeps its old
                # signature and the next run picks it up.
                logger.warning("Could not embed turn %s", turn.id, exc_info=True)
                continue
            turn.embedding_model = signature
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
        help="report how many turns are outside the current space, change nothing",
    )
    args = parser.parse_args(argv)
    embedded = asyncio.run(backfill(args.batch_size, args.limit, args.dry_run))
    print(f"embedded {embedded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
