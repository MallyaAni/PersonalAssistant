"""Verify completed continuation forecasts or run its preregistered funded screen."""

import argparse
import json
from pathlib import Path

from backend.market import nonlinear_continuation_evaluation as screen


# Require explicit evidence identities and fresh private outputs for either phase.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    export = sub.add_parser("verify-forecasts")
    for name in ("prepared", "fitted", "output"):
        export.add_argument("--" + name, type=Path, required=True)
    export.add_argument("--manifest-sha256", required=True)
    run = sub.add_parser("execute")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--config-sha256", required=True)
    verify = sub.add_parser("verify-accounts")
    verify.add_argument("--config", type=Path, required=True)
    verify.add_argument("--config-sha256", required=True)
    verify.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "verify-forecasts":
        value = screen.export_verified(
            args.prepared, args.fitted, args.manifest_sha256, args.output
        )
        print(json.dumps({"months_verified": len(value["months"]),
                          "adoption_eligible": False}), flush=True)
    elif args.phase == "execute":
        screen.execute(screen.checked_json(args.config, args.config_sha256))
    else:
        result = screen.verify_accounts(
            screen.checked_json(args.config, args.config_sha256), args.output
        )
        print(json.dumps({"accounts_verified": len(result["accounts"]),
                          "adoption_eligible": False}), flush=True)


if __name__ == "__main__":
    main()
