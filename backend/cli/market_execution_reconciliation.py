"""Verify preserved decisions and receipts without orders, inference or replay."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from backend.market.execution_reconciliation_audit import (
    audit_saved,
    file_hash,
    require,
)


# Audit explicit saved captures and write only a fresh independent evidence file.
def verify(args):
    output = Path(args.output)
    require(
        not output.exists() and not output.is_symlink(), "Fresh proof file required"
    )
    require(
        all(
            not output.resolve().is_relative_to(Path(root).resolve())
            for root in (args.original_root, args.later_root)
        ),
        "Proof must remain outside original captures",
    )
    result = audit_saved(
        args.original_root,
        args.later_root,
        args.original_proof_sha256,
        args.later_proof_sha256,
    )
    result["audited_at"] = datetime.now(UTC).isoformat()
    result["audit_source_sha256"] = file_hash(
        Path(__file__).parents[1] / "market/execution_reconciliation_audit.py"
    )
    result["cli_source_sha256"] = file_hash(__file__)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as handle:
        json.dump(result, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(
        json.dumps(
            {
                "proof_sha256": file_hash(output),
                "status": result["status"],
                "orders": len(result["orders"]),
                "learned_intraday_path": result["learned_intraday_path"],
            }
        ),
        flush=True,
    )
    return result


# Require independently anchored saved-capture hashes and a separate proof destination.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-root", "later-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("original-proof-sha256", "later-proof-sha256"):
        parser.add_argument("--" + name, required=True)
    verify(parser.parse_args())


if __name__ == "__main__":
    main()
