"""Drive the image scenarios through the real chat API, end to end.

    docker compose exec backend python -m backend.cli.exercise_image_scenarios

The path a browser or the iMessage worker takes - the real router, referent
resolution, lineage, the vision model, and the desktop's ComfyUI - for a
throwaway user in one conversation:

  1. generate a picture
  2. edit it in chat with nothing selected (the newest visible picture)
  3. upload a picture and ask about it
  4. edit the upload with nothing selected (it is now the newest)
  5. explicit selection of the FIRST picture (`active_image_artifact_id`)
  6. refer back by description with nothing selected ("the bicycle picture")
  7. a question about a picture (answered in words, no artifact)

Then everything the user owns is deleted. One verdict line per scenario with
its event trail, and a non-zero exit if any failed. This found four defects
on 2026-08-25 that every structural suite had passed over - the value is in
the whole path, so keep the scenarios end to end and assert on lineage.
Needs the image provider reachable; with the desktop off, scenario 1 fails
with the honest unavailability message and the run stops there.
"""

import argparse
import asyncio
import io
import json
import sys
import uuid

import httpx
from PIL import Image, ImageDraw

from backend.core.auth import issue_user_token

TIMEOUT = httpx.Timeout(600.0, connect=10.0)


def _id(payload: dict | None) -> str | None:
    if not payload:
        return None
    return (
        payload.get("artifact_id")
        or payload.get("id")
        or (payload.get("artifact") or {}).get("id")
    )


# A small synthetic picture - a flag - so an upload is a real PNG the vision
# model can describe without depending on any file on disk.
def _upload_png() -> bytes:
    image = Image.new("RGB", (768, 512), (40, 120, 200))
    draw = ImageDraw.Draw(image)
    draw.ellipse((260, 130, 500, 380), fill=(240, 200, 40))
    draw.rectangle((0, 400, 768, 512), fill=(60, 160, 70))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class Scenarios:
    # One throwaway user, one conversation, one bearer token.
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        self.user = f"image_e2e_{uuid.uuid4().hex[:8]}"
        self.headers = {"Authorization": f"Bearer {issue_user_token(self.user, ttl_seconds=3600)}"}
        self.conversation = str(uuid.uuid4())
        self.failures = 0

    # POST one turn, read the SSE stream, keep the events that matter.
    async def chat(self, client: httpx.AsyncClient, query: str, active: str | None = None) -> dict:
        body = {"user_id": self.user, "conversation_id": self.conversation, "query": query}
        if active:
            body["active_image_artifact_id"] = active
        seen: dict = {"events": [], "artifact": None, "error": None, "text": "", "action": None}
        async with client.stream("POST", f"{self.base}/chat", json=body, headers=self.headers) as response:
            if response.status_code != 200:
                seen["error"] = f"HTTP {response.status_code}: {(await response.aread())[:300]!r}"
                return seen
            event = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event:
                    try:
                        data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if not seen["events"] or seen["events"][-1] != event:
                        seen["events"].append(event)
                    if event == "artifact_ready":
                        seen["artifact"] = data
                    elif event == "artifact_error":
                        seen["error"] = data
                    elif event == "action":
                        seen["action"] = data
                    elif event == "delta":
                        seen["text"] += str(data.get("delta") or data.get("content") or data.get("text") or "")
                    elif event == "error":
                        seen["error"] = data
        return seen

    async def artifact(self, client: httpx.AsyncClient, artifact_id: str | None) -> dict:
        if not artifact_id:
            return {}
        response = await client.get(f"{self.base}/artifacts/{self.user}/{artifact_id}", headers=self.headers)
        return response.json() if response.status_code == 200 else {"_status": response.status_code}

    def verdict(self, name: str, ok: bool, detail: str) -> None:
        if not ok:
            self.failures += 1
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}", flush=True)

    @staticmethod
    def trail(r: dict) -> str:
        return (
            f"events={r['events']} action={str(r['action'])[:90]} "
            f"text={r['text'][:90]!r} err={str(r['error'])[:160]}"
        )

    async def run(self, keep: bool) -> int:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            print(f"user={self.user} conversation={self.conversation}", flush=True)

            r = await self.chat(client, "make me a picture of a red bicycle leaning against a brick wall")
            first = _id(r["artifact"])
            self.verdict("1 generate", bool(first) and not r["error"], f"artifact={first} {self.trail(r)}")
            if not first:
                return 1

            r = await self.chat(client, "add a yellow umbrella leaning next to the bicycle")
            second = _id(r["artifact"])
            meta = await self.artifact(client, second)
            self.verdict(
                "2 edit newest (generated)",
                bool(second) and meta.get("parent_artifact_id") == first,
                f"artifact={second} parent={meta.get('parent_artifact_id')} expected={first} {self.trail(r)}",
            )

            files = {"image": ("scene.png", _upload_png(), "image/png")}
            data = {
                "user_id": self.user,
                "conversation_id": self.conversation,
                "prompt": "what is in this picture?",
                "defer_reasoning": "false",
            }
            up = await client.post(f"{self.base}/vision/analyze", data=data, files=files, headers=self.headers)
            up_json = up.json() if up.status_code in (200, 201) else {}
            uploaded = _id(up_json)
            answer = str(up_json.get("answer") or up_json.get("content") or up_json.get("analysis") or "")[:120]
            self.verdict(
                "3 upload + ask",
                up.status_code in (200, 201) and bool(uploaded),
                f"HTTP {up.status_code} artifact={uploaded} answer={answer!r}",
            )

            r = await self.chat(client, "make the background of this picture purple")
            fourth = _id(r["artifact"])
            meta = await self.artifact(client, fourth)
            self.verdict(
                "4 edit newest (uploaded)",
                bool(fourth) and meta.get("parent_artifact_id") == uploaded,
                f"artifact={fourth} parent={meta.get('parent_artifact_id')} expected={uploaded} {self.trail(r)}",
            )

            r = await self.chat(client, "make the wall white", active=first)
            fifth = _id(r["artifact"])
            meta = await self.artifact(client, fifth)
            self.verdict(
                "5 explicit selection edits the chosen picture",
                bool(fifth) and meta.get("parent_artifact_id") == first,
                f"artifact={fifth} parent={meta.get('parent_artifact_id')} expected={first} {self.trail(r)}",
            )

            r = await self.chat(client, "edit the bicycle picture: put a basket on the front of the bicycle")
            sixth = _id(r["artifact"])
            meta = await self.artifact(client, sixth)
            lineage = {x for x in (first, second, fifth) if x}
            self.verdict(
                "6 referring back by description",
                bool(sixth) and meta.get("parent_artifact_id") in lineage,
                f"artifact={sixth} parent={meta.get('parent_artifact_id')} expected_in={sorted(lineage)} {self.trail(r)}",
            )

            r = await self.chat(client, "what colour is the bicycle in the first picture?")
            self.verdict(
                "7 question about a picture is answered, not edited",
                r["artifact"] is None and not r["error"] and len(r["text"]) > 0,
                self.trail(r),
            )

            r = await self.chat(client, "can you show me the bicycle picture again?")
            shown = _id(r["artifact"])
            self.verdict(
                "8 show an existing picture again",
                bool(shown) and shown in lineage | {sixth} and not r["error"],
                f"artifact={shown} expected_in={sorted(lineage | {sixth})} {self.trail(r)}",
            )

            r = await self.chat(client, "can you regenerate the bicycle picture?")
            regenerated = _id(r["artifact"])
            meta = await self.artifact(client, regenerated)
            self.verdict(
                "9 regenerate makes a new picture",
                bool(regenerated) and regenerated not in lineage | {sixth, uploaded, fourth}
                and meta.get("kind") == "generated_image" and not r["error"],
                f"artifact={regenerated} kind={meta.get('kind')} {self.trail(r)}",
            )

            r = await self.chat(client, "make me a picture of a wooden shop sign that says OPEN in big letters")
            signed = _id(r["artifact"])
            read_back = ""
            if signed:
                content = await client.get(
                    f"{self.base}/artifacts/{self.user}/{signed}/content", headers=self.headers
                )
                if content.status_code == 200:
                    look = await client.post(
                        f"{self.base}/vision/analyze",
                        data={
                            "user_id": self.user,
                            "conversation_id": str(uuid.uuid4()),
                            "prompt": "What text is written in this image? Reply with the exact letters only.",
                            "defer_reasoning": "false",
                        },
                        files={"image": ("sign.png", content.content, "image/png")},
                        headers=self.headers,
                    )
                    look_json = look.json() if look.status_code in (200, 201) else {}
                    read_back = str(
                        look_json.get("answer") or look_json.get("content") or look_json.get("analysis") or ""
                    )
            self.verdict(
                "10 writing in a generated picture is English",
                bool(signed) and "open" in read_back.lower(),
                f"artifact={signed} vlm_read={read_back[:80]!r} {self.trail(r)}",
            )

            if keep:
                print(f"kept: user {self.user} and its artifacts remain for inspection", flush=True)
            else:
                deleted = await client.delete(f"{self.base}/memory/{self.user}", headers=self.headers)
                after = await client.get(f"{self.base}/artifacts/{self.user}", headers=self.headers)
                print(
                    f"cleanup: delete-all HTTP {deleted.status_code}; "
                    f"artifacts after HTTP {after.status_code} {after.text[:40]!r}",
                    flush=True,
                )
        return 1 if self.failures else 0


# Entry point; exit status says whether every scenario passed.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1", help="the backend API root, as seen from where this runs")
    parser.add_argument("--keep", action="store_true", help="leave the throwaway user and its pictures in place for inspection")
    arguments = parser.parse_args(argv)
    return asyncio.run(Scenarios(arguments.base_url).run(keep=arguments.keep))


if __name__ == "__main__":
    sys.exit(main())
