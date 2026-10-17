# Installed trading approval is a release requirement

The October 14 ordinary job rejected an API source digest that a frontend delivery had not reapproved. A preserved model directory and a healthy gateway did not establish that the installed policy admitted the serving source. This candidate makes actual host and container `learned_live_holding.read_configuration` admission a mandatory release boundary.

## Release sequence

1. Run the existing unit and real routing gates against the candidate tree.
2. In that same candidate tree, check the installed configuration against the candidate source before moving the deployment checkout. An exact, separately reviewed approval bundle is required if installed approval is stale.
3. Move the checkout and build images through the existing canonical deployment script.
4. Perform the existing backup and migration sequence, before changing approval selectors.
5. Immediately before the first service restart, if explicitly supplied, archive original config/release/evidence bytes and activate only the reviewed release/config bytes under the existing paper lock. Evidence is never rewritten. This avoids holding a new approval against the old backend throughout a long backup.
6. Require actual host and container admission outputs, including all guarded source hashes and three selector hashes, to match exactly before writing the deployment marker or activating event recovery. Both cheap and full post-deploy paths repeat admission before reporting green.

`--skip-post`, frontend-only releases and `--skip-gate` do not skip admission. An absent host learned configuration is an explicit `NOT_CONFIGURED` no-op. The helper does not run model inference, prepare a decision, read a broker account, or submit orders.

An unrestarted release failure restores exact archived selectors before the old checkout is restored. Rollback refuses a changed current selector or corrupted archive. A failure after restart remains a failed release requiring diagnosis; it does not claim green or automatically move running services back.

## First guarded upgrade

The old installed deployment script cannot enforce a check it does not contain. Invoke the exact new candidate script from its private checkout, pointing it at the actual deployment directory:

```sh
ANIOS_TRADING_PYTHON=/home/animallya96/research-venv/bin/python \
ANIOS_TRADING_APPROVAL_BUNDLE=/absolute/private/reviewed-bundle.json \
ANIOS_TRADING_APPROVAL_BUNDLE_SHA256=<exact-bundle-file-sha256> \
bash /absolute/private/candidate/scripts/deploy.sh \
  --deploy-dir=/home/animallya96/deploy/anios
```

The normal target-resolution rules still apply: the private script does not choose a different target commit. Its preflight loads the helper from the target's gate worktree while the actual deploy checkout remains on the old revision. After checkout, activation and actual admission use the new installed helper. No checkout movement precedes the gates.

## Explicit approval bundle

Environment inputs are `ANIOS_TRADING_APPROVAL_BUNDLE` and `ANIOS_TRADING_APPROVAL_BUNDLE_SHA256`, supplied together. `ANIOS_TRADING_PYTHON` chooses the host interpreter; its default is `$HOME/research-venv/bin/python` when executable, otherwise `python3`. `ANIOS_TRADING_APPROVAL_ARCHIVE_DIR` optionally overrides the default `data/trading-approval-archives`, outside the market artifact tree. There is no arbitrary shell hook and no generated approval.

```json
{
  "schema": "learned-holding-approval-bundle/1",
  "target_revision": "<exact full candidate commit>",
  "review_path": "docs/research/<committed-exact-source-review>.json",
  "review_sha256": "<exact committed review bytes>",
  "predecessor": {
    "config_sha256": "<exact original config bytes>",
    "release_sha256": "<exact original release bytes>",
    "evidence_sha256": "<exact original evidence bytes>"
  },
  "config_json": "<exact reviewed UTF-8 config text>",
  "release_json": "<exact reviewed UTF-8 release text>",
  "evidence_json": "<exact unchanged original UTF-8 evidence text>"
}
```

The bundle file hash is pinned before decoding. The review must exist unchanged in the exact candidate Git commit, with its own pinned hash. Config may change only `release_receipt_sha256`; release may change only `source_sha256` and genuine `approved_at`. Original model/risk/timing identities, policy, costs and economic evidence must remain identical. The existing admission code independently validates the candidate selectors and actual current source map, including rejection of future approval timestamps.

Supported reviews are deliberately narrow:

- `REVIEWED_EXACT_SERVING_SOURCE_APPROVAL_CANDIDATE`: one exact API hash transition, with all other guarded sources unchanged.
- `REVIEWED_EXACT_SERVING_SOURCE_GUARD_EXTENSION`: the exact API, holding-source-list and new read-only decision-module transitions declared in `source_changes`, adding only `backend/market/live_model_decision.py`. All existing holding functions except `source_identity` must match the original reviewed AST hashes. The release source map must exactly match the candidate's actual map.

A later API revision requires its own exact reviewed transition. These schemas do not approve a future hash, wildcard a module, or assert model equivalence in place of comparing evidence.

## Scope and proof limits

The candidate's automated checks exercise the real shell deploy sequence in throwaway Git repositories with deterministic external-command fixtures, plus the real source-admission function against temporary selector files. They cover a stale approval before checkout, healthy-route/failed-admission behavior, explicit activation order, failed gates, migration rollback, first-upgrade bootstrap, frontend and cheap-post paths, selector races and corruptions.

These tests do not establish production deployment, current inference correctness, fresh ordinary acceptance, or historical-account publication. Those remain separate acceptance boundaries, and the original failed dated records and running retrospective account remain unchanged.
