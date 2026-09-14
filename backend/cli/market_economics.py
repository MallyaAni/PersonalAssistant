"""Collect forward economic evidence and a research-only DeepSeek assessment."""

import argparse
from pathlib import Path

from backend.agents.trading.desk import economist
from backend.config.settings import settings
from backend.core.llm import OpenAICompatibleInferenceProvider
from backend.market import economics


# Preserve dated evidence and model provenance without modifying any portfolio state.
def refresh(root: Path, llm_url: str = "", llm_model: str = "") -> dict:
    snapshot = economics.collect()
    model = llm_model or settings.MAIN_LLM_MODEL or settings.LLM_MODEL
    previous = economics.load(root)
    writer = OpenAICompatibleInferenceProvider(
        llm_url or settings.MAIN_LLM_BASE_URL or settings.LLM_BASE_URL,
        model,
        settings.LLM_API_KEY,
        timeout_seconds=60.0,
    )
    cached = (previous or {}).get("assessment") or {}
    snapshot["assessment"] = (
        cached
        if (
            previous
            and previous.get("content_sha256") == snapshot["content_sha256"]
            and previous.get("model") == model
            and cached.get("prompt_version") == economist.VERSION
            and cached.get("status") == "model_assessment"
            and previous.get("facts") == snapshot["facts"]
        )
        else economist.assess(snapshot["facts"], writer)
    )
    snapshot["model"] = model
    economics.save(root, snapshot)
    return snapshot


# Collect outside historical decisions, without backfilling revised inputs.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    parser.add_argument("--llm-url", default="")
    parser.add_argument("--llm-model", default="")
    args = parser.parse_args()
    result = refresh(args.data_dir, args.llm_url, args.llm_model)
    print(f"Economic evidence collected {result['observed_at']}; research context only")


# Keep collection failures from preventing completion of the existing nightly record.
def refresh_if_current(
    root: Path, enabled: bool, llm_url: str = "", llm_model: str = ""
) -> None:
    if not enabled:
        return
    try:
        refresh(root, llm_url, llm_model)
    except Exception as exc:  # noqa: BLE001 - retain dated prior evidence
        print(
            f"Economic context unavailable ({type(exc).__name__}); prior date retained"
        )


if __name__ == "__main__":
    main()
