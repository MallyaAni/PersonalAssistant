"""Render docs/evals/index.html from the committed eval results.

The judged comparison is a decision record, and a decision record nobody can
read is not one. This turns the verbatim answers and blind verdicts in
docs/evals/results/ into a browsable page: scoreboard, per-category table,
and every case with both answers unabridged.

Trying a new candidate is three steps: collect its answers with
`backend.cli.evaluate_reply_quality`, judge them against the incumbent, copy
the two JSONs plus the verdicts into docs/evals/results/ and rerun this
script. models.json carries the measured serving numbers shown in the
profile table - measured on this hardware, never quoted from a card.

    python scripts/build_eval_page.py
"""

import html
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs" / "evals" / "results"
OUT = ROOT / "docs" / "evals" / "index.html"

sys.path.insert(0, str(ROOT))
from backend.services.reply_quality_cases import REPLY_CASES  # noqa: E402

NAME = {"a": "DeepSeek", "b": "Qwen 3.8", "tie": "Tie"}


def esc(text: str) -> str:
    return html.escape(str(text or ""))


def block(label: str, body: str) -> str:
    if not body.strip():
        return ""
    return (
        f'<div class="ctx"><span class="lbl">{esc(label)}</span>'
        f'<div class="ctx-body">{esc(body)}</div></div>'
    )


def main() -> int:
    a = json.loads((RESULTS / "deepseek-v4-flash.json").read_text(encoding="utf-8"))
    b = json.loads(
        (RESULTS / "qwen3.8-27b-bf16-thinking.json").read_text(encoding="utf-8")
    )
    verdicts = json.loads(
        (RESULTS / "verdicts-deepseek-vs-qwen-bf16.json").read_text(encoding="utf-8")
    )
    models = json.loads((RESULTS / "models.json").read_text(encoding="utf-8"))

    cases = [
        c for c in REPLY_CASES if c.prompt in a["answers"] and c.prompt in b["answers"]
    ]
    by_num = {v["case"]: v for v in verdicts}
    tally: dict[str, Counter] = defaultdict(Counter)
    cards = []
    for i, c in enumerate(cases, start=1):
        v = by_num.get(i, {"winner": "tie", "why": ""})
        tally[c.category][v["winner"]] += 1
        evidence = ""
        if c.search:
            evidence = "\n".join(f"{s['title']}: {s['content']}" for s in c.search)
        elif c.recalled_turns:
            evidence = "\n".join(f"said: {t['said']}" for t in c.recalled_turns)
        history = (
            "\n".join(f"user: {q}\nassistant: {r}" for q, r in c.history)
            if c.history
            else ""
        )
        win = v["winner"]
        cards.append(f"""<article class="case" data-winner="{win}">
  <header><span class="num">{i:02d}</span>
    <span class="cat">{esc(c.category.replace("_", " "))}</span>
    <span class="verdict v-{win}">{esc(NAME[win])}</span></header>
  <h3>{esc(c.prompt)}</h3>
  <p class="standard"><span class="lbl">What a good answer does</span>{esc(c.standard)}</p>
  {block("Evidence supplied to both", evidence)}
  {block("Earlier in the conversation", history)}
  <div class="answers">
    <section class="ans a-a{" win" if win == "a" else ""}"><h4>{esc(a["model"])}</h4>
      <div class="prose">{esc(a["answers"][c.prompt])}</div></section>
    <section class="ans a-b{" win" if win == "b" else ""}"><h4>{esc(b["model"])}</h4>
      <div class="prose">{esc(b["answers"][c.prompt])}</div></section>
  </div>
  {f'<p class="why"><span class="lbl">Judge</span>{esc(v.get("why", ""))}</p>' if v.get("why") else ""}
</article>""")

    totals = Counter(by_num[n]["winner"] for n in by_num)
    tally_rows = "".join(
        f"<tr><td>{esc(cat.replace('_', ' '))}</td>"
        f'<td class="n da">{counts["a"] or ""}</td>'
        f'<td class="n qw">{counts["b"] or ""}</td>'
        f'<td class="n mu">{counts["tie"] or ""}</td></tr>'
        for cat, counts in tally.items()
    )
    model_rows = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
        for row in models["rows"]
    )
    model_head = "".join(f"<th>{esc(h)}</th>" for h in models["columns"])

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AniOS model evaluations</title>
<style>
:root{{--bg:#f7f8fa;--card:#fff;--ink:#14161a;--mu:#5c6470;--rule:#e3e6eb;
--da:#a16207;--da-soft:#fbf3e4;--qw:#0e7490;--qw-soft:#e6f4f7;--tie:#6b7280}}
@media(prefers-color-scheme:dark){{:root{{--bg:#101216;--card:#171a1f;--ink:#e7e9ec;
--mu:#949ca8;--rule:#262a31;--da:#d9a441;--da-soft:#241d0f;--qw:#4cb8d0;--qw-soft:#0d2229;--tie:#7c8593}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.6 ui-monospace,Consolas,monospace}}
.wrap{{max-width:1180px;margin:0 auto;padding:3rem 1.5rem 6rem}}
header.top{{border-bottom:2px solid var(--ink);padding-bottom:1.2rem;margin-bottom:2rem}}
h1{{font-size:1.5rem;margin:0 0 .4rem}}h2{{font-size:1.05rem;margin:2.5rem 0 .8rem}}
.sub{{color:var(--mu);font-size:.8rem;margin:0}}
.score{{display:flex;gap:2.5rem;margin:2rem 0;flex-wrap:wrap}}
.score .big{{font-size:2.5rem;font-weight:600;line-height:1}}
.score .lbl{{display:block;font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;color:var(--mu)}}
.s-a .big{{color:var(--da)}}.s-b .big{{color:var(--qw)}}.s-t .big{{color:var(--tie)}}
.note{{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--ink);
padding:1rem 1.15rem;margin:0 0 2rem;font-size:.85rem}}
table{{width:100%;border-collapse:collapse;font-size:.82rem;margin-bottom:2rem}}
th{{text-align:left;font-size:.68rem;text-transform:uppercase;letter-spacing:.09em;
color:var(--mu);padding:.5rem .6rem;border-bottom:1px solid var(--rule)}}
td{{padding:.45rem .6rem;border-bottom:1px solid var(--rule)}}
td.n{{text-align:right;width:5.5rem;font-variant-numeric:tabular-nums}}
td.da{{color:var(--da);font-weight:600}}td.qw{{color:var(--qw);font-weight:600}}td.mu{{color:var(--mu)}}
.filters{{display:flex;gap:.6rem;align-items:center;position:sticky;top:0;background:var(--bg);
padding:.9rem 0;border-bottom:1px solid var(--rule);margin-bottom:1.75rem;z-index:5}}
button{{font:inherit;font-size:.78rem;color:var(--ink);background:var(--card);
border:1px solid var(--rule);border-radius:2px;padding:.35rem .7rem;cursor:pointer}}
button[aria-pressed="true"]{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.count{{font-size:.72rem;color:var(--mu);margin-left:auto}}
.case{{background:var(--card);border:1px solid var(--rule);padding:1.4rem 1.5rem;margin-bottom:1.5rem}}
.case header{{display:flex;align-items:center;gap:.8rem;margin-bottom:.9rem}}
.num{{font-size:.72rem;color:var(--mu)}}
.cat{{font-size:.68rem;text-transform:uppercase;letter-spacing:.09em;color:var(--mu)}}
.verdict{{margin-left:auto;font-size:.7rem;font-weight:600;padding:.2rem .55rem;
text-transform:uppercase;letter-spacing:.06em}}
.v-a{{color:var(--da);background:var(--da-soft)}}.v-b{{color:var(--qw);background:var(--qw-soft)}}
.v-tie{{color:var(--tie);border:1px solid var(--rule)}}
.case h3{{font:600 1.15rem/1.35 Georgia,serif;margin:0 0 .8rem}}
.lbl{{display:block;font-size:.64rem;text-transform:uppercase;letter-spacing:.1em;
color:var(--mu);margin-bottom:.25rem}}
.standard{{font-size:.8rem;color:var(--mu);margin:0 0 1rem}}
.ctx{{margin-bottom:.9rem}}
.ctx-body{{font-size:.76rem;color:var(--mu);white-space:pre-wrap;max-height:7rem;
overflow-y:auto;border-left:2px solid var(--rule);padding-left:.7rem}}
.answers{{display:grid;grid-template-columns:1fr 1fr;gap:1.1rem;margin-top:1.1rem}}
@media(max-width:760px){{.answers{{grid-template-columns:1fr}}}}
.ans{{border-top:2px solid var(--rule);padding-top:.7rem}}
.ans h4{{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;margin:0 0 .5rem}}
.a-a h4{{color:var(--da)}}.a-b h4{{color:var(--qw)}}
.a-a.win{{border-top-color:var(--da)}}.a-b.win{{border-top-color:var(--qw)}}
.prose{{font:.95rem/1.62 Georgia,serif;white-space:pre-wrap}}
.why{{margin:1.1rem 0 0;padding-top:.8rem;border-top:1px dashed var(--rule);
font-size:.78rem;color:var(--mu)}}
.hidden{{display:none}}
a{{color:var(--qw)}}
</style></head><body><div class="wrap">
<header class="top"><h1>Model evaluations</h1>
<p class="sub">Blind, position-swapped judging over this system's own labelled cases
&middot; every number measured on this hardware &middot; regenerated by
<code>scripts/build_eval_page.py</code> &middot; back to the
<a href="../architecture.html">architecture page</a></p></header>

<h2>The decision</h2>
<p class="note">{esc(models["decision"])}</p>

<h2>Serving profile — measured, not quoted</h2>
<table><thead><tr>{model_head}</tr></thead><tbody>{model_rows}</tbody></table>

<h2>Reply quality: {esc(a["model"])} vs {esc(b["model"])}</h2>
<div class="score">
  <div class="s-a"><span class="big">{totals.get("a", 0)}</span><span class="lbl">{esc(a["model"])}</span></div>
  <div class="s-b"><span class="big">{totals.get("b", 0)}</span><span class="lbl">{esc(b["model"])}</span></div>
  <div class="s-t"><span class="big">{totals.get("tie", 0)}</span><span class="lbl">tie</span></div>
</div>
<p class="note"><strong>Read the cells, not the total.</strong> The aggregate favours the
challenger on grounding; the categories matching real use here - weighing options,
committing to a view - go the other way, which is what decided it. Answers are
verbatim and unabridged.</p>
<table><thead><tr><th>Category</th><th class="n">DeepSeek</th><th class="n">Qwen</th><th class="n">Tie</th></tr></thead>
<tbody>{tally_rows}</tbody></table>

<div class="filters">
  <button data-f="all" aria-pressed="true">All</button>
  <button data-f="a" aria-pressed="false">DeepSeek won</button>
  <button data-f="b" aria-pressed="false">Qwen won</button>
  <button data-f="tie" aria-pressed="false">Ties</button>
  <span class="count" id="count"></span>
</div>
<div>{"".join(cards)}</div>
</div>
<script>
const cases=[...document.querySelectorAll('.case')];
const buttons=[...document.querySelectorAll('[data-f]')];
const count=document.getElementById('count');
function apply(f){{let shown=0;for(const c of cases){{const ok=f==='all'||c.dataset.winner===f;
c.classList.toggle('hidden',!ok);if(ok)shown++;}}
count.textContent=shown+' of '+cases.length+' shown';}}
for(const b of buttons)b.addEventListener('click',()=>{{
for(const o of buttons)o.setAttribute('aria-pressed',String(o===b));apply(b.dataset.f);}});
apply('all');
</script></body></html>"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT} ({len(page):,} chars, {len(cases)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
