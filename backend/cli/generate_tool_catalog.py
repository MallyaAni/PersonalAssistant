"""Write docs/TOOL_CATALOG.md from the tool rows.

    python -m backend.cli.generate_tool_catalog

Run it after adding, renaming, or regrouping a tool. The test that compares
the committed page against a fresh render will tell you when you forgot.
"""
import argparse
from pathlib import Path

from backend.tools.catalog_page import render

PAGE = Path("docs/TOOL_CATALOG.md")


# Write the page, or say whether it is already current.
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only report drift")
    arguments = parser.parse_args()

    fresh = render()
    current = PAGE.read_text() if PAGE.exists() else ""
    if fresh == current:
        print(f"{PAGE} is current")
        return 0
    if arguments.check:
        print(f"{PAGE} is out of date; run python -m backend.cli.generate_tool_catalog")
        return 1
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(fresh)
    print(f"wrote {PAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
