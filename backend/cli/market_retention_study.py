"""Run the frozen held-B research comparison using explicit read-only inputs."""

import argparse

from backend.market.retention_study import run


# Require explicit original input paths and a fresh output directory for one fixed run.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "provenance",
        "daily-dir",
        "output",
        "source-revision",
        "source-manifest",
    ):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    run(
        args.snapshot,
        args.provenance,
        args.daily_dir,
        args.output,
        args.source_revision,
        args.source_manifest,
    )


if __name__ == "__main__":
    main()
