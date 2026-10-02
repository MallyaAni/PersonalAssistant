"""Pinned, CPU-only research forecasts; never imported by the live allocator.

The price target is a ten-session terminal adjusted-close forecast. It is not
an executable fill. The TTM target is instead ten-session mean squared daily
log return. Publication and training provenance are reported separately.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

HORIZON = 10
CONTEXT = 252
NY = ZoneInfo("America/New_York")
PROTOCOL = "open-source-forecast/1"


@dataclass(frozen=True)
class Checkpoint:
    name: str
    repository: str
    revision: str
    available_on: str
    license: str
    target: str = "terminal_close"


CHECKPOINTS = {
    "chronos2": Checkpoint(
        "chronos2",
        "amazon/chronos-2",
        "29ec3766d36d6f73f0696f85560a422f50e8498c",
        "2026-06-06",
        "apache-2.0",
    ),
    "kronos": Checkpoint(
        "kronos",
        "NeoQuasar/Kronos-small",
        "901c26c1332695a2a8f243eb2f37243a37bea320",
        "2025-09-10",
        "mit",
    ),
    "timesfm3": Checkpoint(
        "timesfm3",
        "google/timesfm-3.0-pytorch",
        "43046b85ec22d584a13f8098c2ed39c889e129c2",
        "2026-09-03",
        "timesfm-non-commercial-license-v1.0",
    ),
    "ttm": Checkpoint(
        "ttm",
        "ibm-granite/granite-timeseries-ttm-r2",
        "6e5cb8ee51e0634a45637490f5db43148b2fa6be",
        "2025-02-27",
        "apache-2.0",
        "mean_squared_log_return",
    ),
}
TOKENIZER = (
    "NeoQuasar/Kronos-Tokenizer-base",
    "0e0117387f39004a9016484a186a908917e22426",
)
CODE_REVISIONS = {
    "kronos": "67b630e67f6a18c9e9be918d9b4337c960db1e9a",
    "timesfm3": "e51928e27119cb17bebc005be2696b75e0a9e688",
}


# Parse source observation times without silently assigning a timezone.
def aware(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("available_at requires an explicit timezone")
    return result


# Hash causal input content so a forecast can be matched to its exact evidence.
def digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


# Build a completed-session prefix and reject mixed bases, gaps and duplicates.
def context(payload: dict, symbol: str, decision: str) -> tuple[list[dict], list[str]]:
    if payload.get("price_basis") != "adjusted_ohlcv" or not payload.get(
        "source_revision"
    ):
        raise ValueError("explicit adjusted OHLCV and source revision are required")
    if payload.get("availability_mode") not in ("recorded", "session_close_assumed"):
        raise ValueError("explicit original or assumed availability mode is required")
    if not payload.get("volume_basis") or not payload.get("data_mode"):
        raise ValueError("volume basis and data provenance mode are required")
    calendar = payload["calendar"]
    if calendar != sorted(set(calendar)):
        raise ValueError("calendar must be unique and sorted")
    end = calendar.index(decision)
    expected = calendar[max(0, end - CONTEXT + 1) : end + 1]
    if len(expected) != CONTEXT:
        raise ValueError("252 completed exchange sessions are required")
    cutoff = datetime.combine(date.fromisoformat(decision), time(16), NY)
    selected = [
        r
        for r in payload["rows"]
        if r["symbol"] == symbol
        and r["session"] in expected
        and aware(r["available_at"]) <= cutoff
    ]
    selected.sort(key=lambda r: r["session"])
    if [r["session"] for r in selected] != expected:
        raise ValueError("missing, duplicated or unavailable history")
    for row in selected:
        prices = np.array(
            [row[k] for k in ("open", "high", "low", "close")], dtype=float
        )
        volume = float(row["volume"])
        if (
            not np.isfinite(prices).all()
            or (prices <= 0).any()
            or not np.isfinite(volume)
            or volume < 0
            or row["high"] < max(row["open"], row["close"])
            or row["low"] > min(row["open"], row["close"])
        ):
            raise ValueError("invalid adjusted OHLCV")
    future = calendar[end + 1 : end + HORIZON + 1]
    if len(future) != HORIZON:
        raise ValueError("ten known future exchange dates are required")
    return selected, future


# Download only immutable configuration and safetensors, never remote code/pickle.
def snapshot(repository: str, revision: str) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(
        repository,
        revision=revision,
        allow_patterns=["config.json", "*.safetensors", "LICENSE"],
    )


class Forecaster:
    """Load one reviewed pretrained model lazily, then forecast causal prefixes."""

    # Require explicit research licensing and keep every computation on the CPU.
    def __init__(self, name: str, *, research_only: bool = False):
        self.spec = CHECKPOINTS[name]
        if name == "timesfm3" and not research_only:
            raise ValueError("TimesFM3 requires explicit noncommercial research mode")
        self.model = None
        self.cache: dict[str, np.ndarray] = {}
        self.runtime: dict[str, str] = {}

    # Construct official local implementations with immutable safe checkpoint paths.
    def load(self) -> None:
        import torch

        self.runtime = {"torch": torch.__version__, "numpy": np.__version__}
        package = {
            "chronos2": "chronos-forecasting",
            "timesfm3": "timesfm",
            "ttm": "granite-tsfm",
        }.get(self.spec.name)
        if package:
            self.runtime[package] = importlib.metadata.version(package)
        torch.set_num_threads(2)
        torch.manual_seed(0)
        path = snapshot(self.spec.repository, self.spec.revision)
        if self.spec.name == "chronos2":
            from chronos import Chronos2Pipeline

            self.model = Chronos2Pipeline.from_pretrained(path, device_map="cpu")
        elif self.spec.name == "kronos":
            # Parent installs the reviewed official checkout; no dynamic remote loader.
            upstream = importlib.import_module("model")
            root = Path(upstream.__file__).resolve().parents[1]
            revision = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            if revision != CODE_REVISIONS["kronos"]:
                raise ValueError(
                    "Kronos requires the reviewed official source revision"
                )
            subprocess.run(
                ["git", "-C", str(root), "diff", "--exit-code"],
                check=True,
                capture_output=True,
            )
            self.runtime["kronos_source_revision"] = revision
            tokenizer = upstream.KronosTokenizer.from_pretrained(
                snapshot(*TOKENIZER)
            ).eval()
            model = upstream.Kronos.from_pretrained(path).eval()
            self.model = upstream.KronosPredictor(
                model, tokenizer, device="cpu", max_context=512
            )
        elif self.spec.name == "timesfm3":
            from timesfm3 import ModelConfig, TimesFM3Evaluator

            url = importlib.metadata.distribution("timesfm").read_text(
                "direct_url.json"
            )
            revision = json.loads(url or "{}").get("vcs_info", {}).get("commit_id")
            if revision != CODE_REVISIONS["timesfm3"]:
                raise ValueError(
                    "TimesFM3 requires the reviewed official source revision"
                )
            self.runtime["timesfm_source_revision"] = revision
            self.model = TimesFM3Evaluator(
                ModelConfig(
                    checkpoint_path=path,
                    device="cpu",
                    per_core_batch_size=1,
                )
            )
        else:
            from tsfm_public.models.tinytimemixer import TinyTimeMixerForPrediction

            self.model = (
                TinyTimeMixerForPrediction.from_pretrained(path).to("cpu").eval()
            )

    # Forecast the declared target with fixed settings and validate its shape/units.
    def predict(self, rows: list[dict], future: list[str]) -> np.ndarray:
        key = digest({"rows": rows, "future": future, "checkpoint": asdict(self.spec)})
        if key in self.cache:
            return self.cache[key].copy()
        if self.model is None:
            self.load()
        import torch

        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        closes = np.array([r["close"] for r in rows], dtype=np.float32)
        with torch.inference_mode():
            result = self._predict(rows, future, closes)
        result = np.asarray(result, dtype=float)
        if result.shape != (HORIZON,) or not np.isfinite(result).all():
            raise ValueError(
                "model returned invalid forecast shape or nonfinite values"
            )
        if self.spec.target == "terminal_close" and (result <= 0).any():
            raise ValueError("model returned nonpositive prices")
        self.cache[key] = result.copy()
        return result

    # Translate only the four documented official inference interfaces.
    def _predict(
        self, rows: list[dict], future: list[str], closes: np.ndarray
    ) -> np.ndarray:
        import torch

        if self.spec.name == "chronos2":
            quantiles, _ = self.model.predict_quantiles(
                [torch.tensor(closes)],
                prediction_length=HORIZON,
                quantile_levels=[0.5],
            )
            return quantiles[0].detach().cpu().numpy().reshape(-1)
        if self.spec.name == "timesfm3":
            outputs = list(
                self.model.predict_batch(
                    [closes],
                    horizon=HORIZON,
                    return_quantiles=True,
                    use_symmetric_averaging=False,
                )
            )
            return np.asarray(outputs[0].quantiles)[..., 4].reshape(-1)
        if self.spec.name == "kronos":
            import pandas as pd

            frame = pd.DataFrame(rows)[["open", "high", "low", "close", "volume"]]
            result = self.model.predict(
                frame,
                pd.Series(pd.to_datetime([r["session"] for r in rows])),
                pd.Series(pd.to_datetime(future)),
                HORIZON,
                T=1.0,
                top_k=0,
                top_p=0.9,
                sample_count=8,
                verbose=False,
            )
            return result["close"].to_numpy()
        # Daily-compatible r2.1 model reads 90 observed squared log returns.
        risk = np.diff(np.log(closes.astype(float)))[-90:] ** 2
        center, scale = float(risk.mean()), float(risk.std())
        scale = scale if scale > 0 else 1.0
        past = torch.tensor((risk - center) / scale, dtype=torch.float32)[None, :, None]
        prediction = self.model(
            past_values=past, freq_token=torch.tensor([8])
        ).prediction_outputs
        return np.maximum(0, prediction[0, :HORIZON, 0].cpu().numpy() * scale + center)


# Retain every requested opportunity and distinguish forecast errors from missing data.
def run(
    payload: dict,
    name: str,
    symbols: list[str],
    *,
    research_only: bool = False,
    forecaster: Forecaster | None = None,
) -> dict:
    spec = CHECKPOINTS[name]
    engine = forecaster or Forecaster(name, research_only=research_only)
    records = []
    for decision in payload["decisions"]:
        for symbol in symbols:
            record: dict[str, Any] = {
                "model": name,
                "symbol": symbol,
                "decision": decision,
                "status": "unavailable",
            }
            records.append(record)
            if decision < spec.available_on:
                record["reason"] = "checkpoint_not_available"
                continue
            try:
                rows, future = context(payload, symbol, decision)
                spy_rows, _ = context(payload, "SPY", decision)
            except ValueError as error:
                record.update(status="unavailable", reason=str(error))
                continue
            try:
                prediction = engine.predict(rows, future)
                record.update(
                    status="forecast",
                    context_hash=digest(rows),
                    last_known_at=rows[-1]["available_at"],
                    horizon_session=future[-1],
                    forecast=prediction.tolist(),
                )
                if spec.target == "terminal_close":
                    spy_prediction = engine.predict(spy_rows, future)
                    record["predicted_return"] = float(
                        prediction[-1] / rows[-1]["close"] - 1
                    )
                    record["predicted_excess_return"] = float(
                        record["predicted_return"]
                        - (spy_prediction[-1] / spy_rows[-1]["close"] - 1)
                    )
                else:
                    record["predicted_risk"] = float(prediction.mean())
                    record["baseline_risk"] = float(
                        np.mean(np.diff(np.log([r["close"] for r in rows[-21:]])) ** 2)
                    )
            except (
                ImportError,
                OSError,
                RuntimeError,
                ValueError,
                subprocess.SubprocessError,
            ) as error:
                record.update(status="model_error", reason=type(error).__name__)
    return {
        "protocol": PROTOCOL,
        "checkpoint": asdict(spec),
        "records": records,
        "source_revision": payload.get("source_revision"),
        "runtime": getattr(engine, "runtime", {}),
        "device": "cpu",
        "seed": 0,
        "availability_mode": payload.get("availability_mode"),
        "volume_basis": payload.get("volume_basis"),
        "data_mode": payload.get("data_mode"),
        "training_cutoff": "not_verified",
        "historical_tradability": "not_established",
        "interpretation": "post_checkpoint_retrospective_forecast_diagnostic",
        "license_allows_production": name != "timesfm3",
        "production_eligible": False,
    }
