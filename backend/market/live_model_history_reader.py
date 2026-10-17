"""Authenticate current-model sized history separately from old model-only research."""

import json
from hashlib import sha256
from pathlib import Path

from backend.market import learned_live_holding
from backend.market import live_model_history_binding as binding
from backend.market import live_model_history_projection as projection
from backend.market.grade_led_policy import POLICY


# Require content digests before using a publication path or identity.
def digest(value):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError("Historical sizing content digest required")
    return value


# Validate one immutable version against the live configuration before selecting it.
def _read_version(root, ticker, manifest):
    root = Path(root)
    folder = root / projection.DIRECTORY
    name = ticker.upper()
    if name not in manifest["files"] or not name.replace("-", "").isalnum():
        raise ValueError("Current-model history unavailable for this ticker")
    version = digest(manifest["version"])
    raw = (folder / version / (name + ".json")).read_bytes()
    if sha256(raw).hexdigest() != digest(manifest["files"][name]):
        raise ValueError("Current-model history projection bytes differ")
    value = json.loads(raw)
    provenance = value["provenance"]
    binding_sha = manifest.get("serving_binding_sha256")
    if binding_sha is not None:
        raw_binding = (folder / version / "serving-binding.json").read_bytes()
        binding.require_hash(raw_binding, digest(binding_sha))
        if provenance.get("serving_binding_sha256") != binding_sha:
            raise ValueError("Historical payload serving binding differs")
        binding.validate(root, json.loads(raw_binding), provenance)
    else:
        if "serving_binding_sha256" in provenance:
            raise ValueError("Historical payload serving binding is missing")
        if provenance["source_sha256"] != learned_live_holding.source_identity():
            raise ValueError("Historical sizing no longer matches live trading source")
        for path, key in (
            ("desk/learned-holding/config.json", "holding_config_sha256"),
            ("desk/learned-timing/config.json", "timing_config_sha256"),
        ):
            if sha256((root / path).read_bytes()).hexdigest() != digest(
                provenance[key]
            ):
                raise ValueError(
                    "Historical sizing no longer matches installed live configuration"
                )
    if (
        manifest["schema"] != projection.SCHEMA
        or value["schema"] != projection.SCHEMA
        or value["policy"] != POLICY
        or value["ticker"] != name
        or value["counterfactual"] is not True
        or value["real_orders"] is not False
        or provenance["basis"] != "fixed_current_models_applied_retrospectively"
        or provenance["cost_bps"] != 10
        or provenance["projection_source_sha256"]
        != sha256(Path(projection.__file__).read_bytes()).hexdigest()
        or provenance["verification"]["status"]
        != "VERIFIED_CURRENT_MODEL_HISTORICAL_ACCOUNT"
        or provenance["verification"]["account_sha256"] != provenance["account_sha256"]
        or provenance["account_sha256"] != manifest["account_sha256"]
        or not isinstance(value["decisions"], list)
        or not isinstance(value["trades"], list)
    ):
        raise ValueError("Verified current-model historical contract differs")
    return value


# Return only verified immutable projections bound to the installed live model versions.
def read(root, ticker):
    manifest = json.loads(
        (Path(root) / projection.DIRECTORY / "manifest.json").read_bytes()
    )
    return _read_version(root, ticker, manifest)
