"""Run joint purchase/cash-exit selection using verified saved model evidence."""

import argparse

from backend.market.cash_selection_study import run


# Require immutable input/control paths and a fresh private output directory.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "provenance",
        "daily-dir",
        "old-directory",
        "proof",
        "public",
        "output",
        "source-revision",
        "source-manifest",
    ):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--attribution", action="store_true")
    for name in ("joint-directory", "joint-proof", "joint-public"):
        parser.add_argument(f"--{name}")
    args = parser.parse_args()
    run(
        args.snapshot,
        args.provenance,
        args.daily_dir,
        args.old_directory,
        args.proof,
        args.public,
        args.output,
        args.source_revision,
        args.source_manifest,
        attribution=args.attribution,
        joint_directory=args.joint_directory,
        joint_proof=args.joint_proof,
        joint_public=args.joint_public,
    )


if __name__ == "__main__":
    main()
