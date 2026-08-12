"""Resolving provenance from the parent edge, against a real PostgreSQL.

The recursive walk, the ownership check at every hop and the depth bound are all
SQL. A fake repository would assert that this module's Python is self-consistent
and say nothing about the query, which is the part that has to be right.

Every test runs inside one transaction that is always rolled back, so nothing is
committed to the database it connects to. It skips rather than fails when there
is no database, the same bargain the functional suite makes about the model.
"""

import json
import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.database.session import ASYNC_DATABASE_URL
from backend.services.artifact_repository import SQLAlchemyArtifactRepository

pytestmark = pytest.mark.asyncio

OWNER = "lineage-test-owner"
STRANGER = "lineage-test-stranger"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(ASYNC_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as opened:
            await opened.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on the host
        await engine.dispose()
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    async with factory() as opened:
        try:
            yield opened
        finally:
            # Nothing here is ever committed, so the rows exist only for the
            # length of this transaction and the database is left untouched.
            await opened.rollback()
            await engine.dispose()


# Insert one artifact directly, so a chain can be built without the write path
# committing it. Returns the id the next link points at.
async def _artifact(
    session: Any,
    *,
    user_id: str = OWNER,
    kind: str = "generated_image",
    title: str = "Edited image",
    parent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    artifact_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO visual_artifacts
                (id, user_id, conversation_id, trace_id, kind, status, title,
                 provider, parent_artifact_id, extra_data, created_at, updated_at)
            VALUES
                (:id, :user_id, :conversation_id, :trace_id, :kind, 'ready',
                 :title, 'test', :parent, CAST(:extra_data AS json), now(), now())
            """
        ).bindparams(
            id=uuid.UUID(artifact_id),
            user_id=user_id,
            conversation_id=uuid.uuid4(),
            trace_id=uuid.uuid4(),
            kind=kind,
            title=title,
            parent=uuid.UUID(parent) if parent else None,
            extra_data=json.dumps(metadata or {}),
        )
    )
    return artifact_id


# The defect this was built for. Only the edit is asked about — the original is
# not among the results, which is exactly the case the previous approach could
# not answer, because it reconstructed lineage from the result set.
async def test_an_edit_names_its_origin_without_the_origin_being_retrieved(
    session: Any,
) -> None:
    upload = await _artifact(
        session,
        kind="uploaded_image",
        title="Uploaded image",
        metadata={"analysis": "A man in a wide-brimmed black cowboy hat."},
    )
    edit = await _artifact(
        session,
        parent=upload,
        metadata={"refinement_feedback": "give me a straw hat"},
    )

    resolved = await SQLAlchemyArtifactRepository(session).resolve_lineage(
        OWNER, [edit]
    )

    lineage = resolved[edit]
    assert lineage.origin["id"] == upload
    assert lineage.supplied_by_user is True
    assert "black cowboy hat" in lineage.origin["description"]
    assert lineage.edits == ("give me a straw hat",)


# An edit of an edit reports the picture the user supplied, not the middle one,
# and the edits read in the order they were applied.
async def test_a_chain_reports_the_root_and_every_edit_in_order(
    session: Any,
) -> None:
    root = await _artifact(
        session,
        kind="uploaded_image",
        metadata={"analysis": "A red bicycle against a wall."},
    )
    first = await _artifact(
        session, parent=root, metadata={"refinement_feedback": "make it blue"}
    )
    second = await _artifact(
        session, parent=first, metadata={"refinement_feedback": "add a basket"}
    )

    resolved = await SQLAlchemyArtifactRepository(session).resolve_lineage(
        OWNER, [second]
    )

    assert resolved[second].origin["id"] == root
    assert resolved[second].edits == ("make it blue", "add a basket")


# One query serves a whole page of matches, each with its own answer.
async def test_several_artifacts_resolve_in_one_call(session: Any) -> None:
    first_root = await _artifact(
        session, kind="uploaded_image", metadata={"analysis": "A lake at dawn."}
    )
    first_edit = await _artifact(
        session, parent=first_root, metadata={"refinement_feedback": "warmer light"}
    )
    second_root = await _artifact(
        session, metadata={"generation_prompt": "a cobalt sports car"}
    )
    second_edit = await _artifact(
        session, parent=second_root, metadata={"refinement_feedback": "make it red"}
    )
    unrelated = await _artifact(session, metadata={"generation_prompt": "a teapot"})

    resolved = await SQLAlchemyArtifactRepository(session).resolve_lineage(
        OWNER, [first_edit, second_edit, unrelated]
    )

    assert resolved[first_edit].origin["description"] == "A lake at dawn."
    assert resolved[first_edit].supplied_by_user is True
    assert resolved[second_edit].origin["description"] == "a cobalt sports car"
    # Generated, not supplied: the distinction the assistant got wrong.
    assert resolved[second_edit].supplied_by_user is False
    # An artifact that is nobody's revision has no lineage rather than an empty
    # one, so a caller cannot mistake "no parent" for "parent unknown".
    assert unrelated not in resolved


# Ownership is enforced at every hop. A stored identifier pointing into another
# account must stop the walk, not describe that account's picture.
async def test_a_chain_never_walks_into_another_users_history(
    session: Any,
) -> None:
    theirs = await _artifact(
        session,
        user_id=STRANGER,
        kind="uploaded_image",
        metadata={"analysis": "Something belonging to somebody else."},
    )
    mine = await _artifact(
        session, parent=theirs, metadata={"refinement_feedback": "make it brighter"}
    )

    resolved = await SQLAlchemyArtifactRepository(session).resolve_lineage(
        OWNER, [mine]
    )

    assert mine not in resolved


# Asking for someone else's artifact returns nothing at all, not their lineage.
async def test_another_users_artifact_resolves_to_nothing(session: Any) -> None:
    theirs_root = await _artifact(session, user_id=STRANGER, kind="uploaded_image")
    theirs_edit = await _artifact(session, user_id=STRANGER, parent=theirs_root)

    resolved = await SQLAlchemyArtifactRepository(session).resolve_lineage(
        OWNER, [theirs_edit]
    )

    assert resolved == {}


# The bound is what stops a cycle in stored data from running forever, so it has
# to actually apply. Walked one step, the answer is the parent, not the root.
async def test_the_depth_bound_stops_the_walk(session: Any) -> None:
    root = await _artifact(
        session, kind="uploaded_image", metadata={"analysis": "The very first one."}
    )
    middle = await _artifact(
        session, parent=root, metadata={"refinement_feedback": "step one"}
    )
    leaf = await _artifact(
        session, parent=middle, metadata={"refinement_feedback": "step two"}
    )

    resolved = await SQLAlchemyArtifactRepository(session).resolve_lineage(
        OWNER, [leaf], max_depth=1
    )

    assert resolved[leaf].origin["id"] == middle
    assert resolved[leaf].edits == ("step two",)


# A malformed identifier is a caller error, not a reason to raise inside a turn.
async def test_unusable_identifiers_resolve_to_nothing(session: Any) -> None:
    repository = SQLAlchemyArtifactRepository(session)

    assert await repository.resolve_lineage(OWNER, []) == {}
    assert await repository.resolve_lineage(OWNER, ["not-a-uuid"]) == {}
