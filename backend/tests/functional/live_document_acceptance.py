"""Live acceptance of document knowledge, driven through the real HTTP API
from inside the backend container after a deploy:

    docker exec -e ITINERARY_PATH=/tmp/itinerary.pdf -w /app anios_backend \
        python -m backend.tests.functional.live_document_acceptance

Uploads the operator's itinerary through the real route (Docling on the
desktop -> knowledge store), asks the real chat endpoint about it, checks the
answer names the document, pins the document for a scoped question, then
says "forget that" and checks the document is gone. Prints PASS/FAIL lines
and exits non-zero on any FAIL. Not a pytest test: it needs a deployed
server, a reachable Docling, and the file, and it changes real state for a
throwaway user.
"""
import asyncio
import json
import os
import sys
import uuid

import httpx

from backend.core.auth import issue_user_token

BASE = os.environ.get("BASE", "http://localhost:8000")
ITINERARY = os.environ.get("ITINERARY_PATH", "/tmp/itinerary.pdf")
passed = failed = 0


def ok(m):
    global passed; passed += 1; print("PASS", m)


def bad(m):
    global failed; failed += 1; print("FAIL", m)


async def chat(client, token, user, conversation, query, **extra):
    body = {"user_id": user, "conversation_id": conversation, "query": query, **extra}
    text = ""
    async with client.stream(
        "POST", f"{BASE}/api/v1/chat", json=body, headers={"Authorization": f"Bearer {token}"}, timeout=300
    ) as response:
        if response.status_code != 200:
            return f"HTTP {response.status_code}: {(await response.aread())[:200]!r}"
        event = ""
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "delta":
                try:
                    payload = json.loads(line.split(":", 1)[1].strip())
                except ValueError:
                    continue
                text += str(payload.get("content") or payload.get("text") or payload.get("delta") or "")
    return text


async def main() -> int:
    user = f"live-doc-{uuid.uuid4().hex[:8]}"
    conversation = str(uuid.uuid4())
    token = issue_user_token(user, ttl_seconds=900, scopes=["chat", "memory:write", "memory:read"])
    headers = {"Authorization": f"Bearer {token}"}
    content = open(ITINERARY, "rb").read()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE}/api/v1/memory/{user}/agent/knowledge/document",
            headers=headers,
            files={"document": ("Itinerary Amalfi Choral Tour.pdf", content, "application/pdf")},
            data={"note": "", "source_conversation_id": conversation},
            timeout=300,
        )
        if r.status_code == 201 and not r.json().get("queued"):
            stored = r.json(); ok(f"upload stored: pages={stored.get('pages')} chunks={stored.get('chunk_count', '?')}")
        else:
            bad(f"upload -> {r.status_code} {r.text[:200]}"); return 1
        doc_id = stored["id"]

        answer = await chat(client, token, user, conversation, "what happens on the evening of day 1 of the amalfi tour?")
        print("   answer:", answer[:240].replace("\n", " "))
        (ok if ("Salerno" in answer or "dinner" in answer.lower()) else bad)("answers from the itinerary (Salerno / dinner)")
        (ok if ("itinerary" in answer.lower() or "Amalfi" in answer or "document" in answer.lower()) else bad)("names the document")

        scoped = await chat(client, token, user, conversation, "which day has the Pompeii excursion?", active_document_id=doc_id)
        print("   pinned answer:", scoped[:200].replace("\n", " "))
        (ok if "Day 2" in scoped or "day 2" in scoped.lower() or "October 12" in scoped else bad)("pinned document answers Day 2 / Oct 12")

        forget = await chat(client, token, user, conversation, "forget that document")
        print("   forget reply:", forget[:160].replace("\n", " "))
        # The proof is the record, not a search miss: a search can come back
        # empty for other reasons (the first four runs passed this way while
        # the document rows survived, 2026-09-02). The document must be gone.
        r = await client.get(f"{BASE}/api/v1/memory/{user}/agent/knowledge/{doc_id}", headers=headers, timeout=60)
        (ok if r.status_code == 404 else bad)(f"after forgetting, the document row is gone (GET -> {r.status_code})")
        if r.status_code != 404:
            # leave nothing behind for the throwaway user
            await client.delete(f"{BASE}/api/v1/memory/{user}/agent/knowledge/{doc_id}", headers=headers, timeout=60)
    print(f"\nRESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
