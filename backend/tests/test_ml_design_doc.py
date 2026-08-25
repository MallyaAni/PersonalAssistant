"""The ML design document must account for every flag the reply model is
served with. The doc once said chunked prefill was off while the engine ran
it on; this keeps the flag table and the serving script from drifting apart
in the direction that can be checked mechanically."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "spark" / "ds4-tp2.sh"
DOC = REPO / "docs" / "ML_SYSTEM_DESIGN.md"

# Plumbing that names the deployment rather than a design choice.
PLUMBING = {
    "--served-model-name",
    "--trust-remote-code",
    "--pipeline-parallel-size",
    "--node-rank",
    "--master-addr",
    "--master-port",
    "--headless",
}


def _serving_flags() -> set[str]:
    """Every `--flag` in the serving script's exec block, plumbing excluded."""
    text = SCRIPT.read_text()
    # Everything after the image name is vLLM's; before it is docker's.
    vllm_args = text[text.index('"$IMAGE"') :]
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", vllm_args)) - PLUMBING


def test_every_serving_flag_has_a_documented_origin():
    doc = DOC.read_text()
    flags = _serving_flags()
    assert flags, "no flags parsed from the serving script"
    missing = sorted(flag for flag in flags if f"`{flag}" not in doc)
    assert not missing, f"serving flags with no entry in ML_SYSTEM_DESIGN.md: {missing}"


def test_the_moe_kernel_selection_is_documented_with_its_guard():
    doc = DOC.read_text()
    assert "flashinfer_b12x" in doc
    assert "VLLM_MOE_USE_DEEP_GEMM=0" in doc, "explain the DeepGEMM priority guard"


def test_the_document_does_not_claim_chunked_prefill_is_off():
    doc = DOC.read_text().lower()
    assert "chunked prefill off" not in doc
    assert "chunked prefill is enabled" in doc
