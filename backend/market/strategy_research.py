"""Read frozen model-only research independently of the active account policy."""

import hashlib
import json
from pathlib import Path

from backend.market import strategy_simulation as simulation


# Preserve exact publication configuration bytes before selecting a new manifest.
def archive_configuration(root, raw):
    digest = hashlib.sha256(raw).hexdigest()
    folder = Path(root) / simulation.DIRECTORY / "configurations"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / (digest + ".json")
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Simulation configuration archive differs")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o600)
    return digest


# Authenticate original research configuration and payloads without reading a broker.
def read(root, ticker=None):
    base = Path(root)
    folder = base / simulation.DIRECTORY
    manifest = json.loads((folder / "manifest.json").read_bytes())
    digest = manifest["config_sha256"]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("Simulation configuration must be a content digest")
    archive = folder / "configurations" / (digest + ".json")
    raw_config = (
        archive.read_bytes()
        if archive.exists()
        else (base / "desk/learned-holding/config.json").read_bytes()
    )
    if hashlib.sha256(raw_config).hexdigest() != digest:
        raise ValueError("Simulation original configuration is unavailable")
    config = json.loads(raw_config)
    if (
        config["policy"] != simulation.POLICY
        or config["cost_bps"] != manifest["cost_bps"]
    ):
        raise ValueError(
            "Simulation policy or costs differ from original configuration"
        )
    name = "summary" if ticker is None else ticker.upper()
    if name not in manifest["files"] or not name.replace("-", "").isalnum():
        raise ValueError("Simulation unavailable for this stock")
    version = manifest["version"]
    if len(version) != 64 or any(char not in "0123456789abcdef" for char in version):
        raise ValueError("Simulation version must be a content digest")
    raw = (folder / version / (name + ".json")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["files"][name]:
        raise ValueError("Simulation projection integrity differs")
    result = json.loads(raw)
    if (
        manifest["schema"] != simulation.SCHEMA
        or result["schema"] != simulation.SCHEMA
        or result["policy"] != simulation.POLICY
        or result["counterfactual"] is not True
        or result["real_orders"] is not False
        or result["provenance"]["config_sha256"] != digest
        or result["provenance"]["cost_bps"] != manifest["cost_bps"]
        or result["provenance"]["projection_source_sha256"]
        != hashlib.sha256(Path(simulation.__file__).read_bytes()).hexdigest()
        or (ticker is not None and result["ticker"] != name)
        or (ticker is not None and not isinstance(result.get("splits"), list))
    ):
        raise ValueError("Simulation projection contract differs")
    return result
