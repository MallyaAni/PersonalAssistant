"""Real CPU neural fitting must not publish an unsupervised output head.

This suite also runs with the standard-library unittest runner on a training
worker without pytest. Pass the source root as its sole script argument when
streaming it to that worker; it prints hashes for the exact exercised modules.
All inputs are synthetic and each fit is one epoch on CPU, never historical data.
"""

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import numpy as np


class HeadSupervisionRuntimeTests(unittest.TestCase):
    """Exercise the actual CNN and PatchTST training and inference paths."""

    # Skip explicitly without Torch instead of treating a missing runtime as a pass.
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec("torch") is None:
            raise unittest.SkipTest("real Torch runtime unavailable")
        import torch

        torch.set_num_threads(1)

    # Fit a real tiny network on deterministic synthetic observations and return scores.
    def fit(self, family, labels):
        from backend.market import deep_intraday as stage1
        from backend.market import deep_stage2_nn as neural

        random = np.random.default_rng(731)
        sequences = random.normal(size=(16, 26, 3)).astype(np.float32)
        scalars = random.normal(size=(16, 3))
        config = dict(stage1.CNN_CONFIG if family == "cnn" else stage1.PATCHTST_CONFIG)
        config.update(epochs=1, batch=12)
        return neural.fit_predict(
            family,
            sequences[:12],
            scalars[:12],
            labels,
            ("mse", "bce", "mse", "bce"),
            sequences[12:],
            scalars[12:],
            config,
            device="cpu",
        )

    # Missing or insufficient labels cannot become a finite score or probability.
    def test_withholds_heads_below_the_existing_minimum(self):
        labels = np.tile([0.1, 1.0, 0.2, 0.0], (12, 1))
        labels[2:, 1] = np.nan
        labels[:, 2] = np.nan
        labels[3:, 3] = np.nan
        for family in ("cnn", "patchtst"):
            with self.subTest(family=family):
                predicted, count = self.fit(family, labels)
                assert predicted.shape == (4, 4)
                assert count > 0
                assert np.isfinite(predicted[:, [0, 3]]).all()
                assert np.isnan(predicted[:, [1, 2]]).all()
                probability = predicted[:, 3]
                assert ((probability >= 0) & (probability <= 1)).all()

    # A network with no supervised output cannot emit plausible-looking random scores.
    def test_withholds_every_head_when_all_labels_are_missing(self):
        for family in ("cnn", "patchtst"):
            with self.subTest(family=family):
                predicted, count = self.fit(family, np.full((12, 4), np.nan))
                assert count > 0
                assert np.isnan(predicted).all()

    # Supervised heads retain finite scores and bounded BCE probabilities.
    def test_preserves_fully_supervised_outputs(self):
        labels = np.tile([0.1, 1.0, 0.2, 0.0], (12, 1))
        for family in ("cnn", "patchtst"):
            with self.subTest(family=family):
                predicted, count = self.fit(family, labels)
                assert count > 0
                assert np.isfinite(predicted).all()
                probabilities = predicted[:, [1, 3]]
                assert ((probabilities >= 0) & (probabilities <= 1)).all()


# Run the same tests on an existing training worker and identify its exact source bytes.
def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_deep_head_supervision_torch.py SOURCE_ROOT")
    root = Path(sys.argv.pop(1)).resolve()
    sys.path.insert(0, str(root))
    import torch

    names = (
        "deep_intraday.py",
        "deep_intraday_cnn.py",
        "deep_intraday_patchtst.py",
        "deep_stage2.py",
        "deep_stage2_nn.py",
    )
    print(
        json.dumps(
            {
                "torch": torch.__version__,
                "device": "cpu",
                "source_sha256": {
                    name: hashlib.sha256(
                        (root / "backend/market" / name).read_bytes()
                    ).hexdigest()
                    for name in names
                },
            },
            sort_keys=True,
        ),
        flush=True,
    )
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
