"""Explicit device selection and portable research checkpoints."""

import pytest

# torch is a research-only dependency, absent from the test image, so the
# module skips there and runs where the research extra is installed.
torch = pytest.importorskip("torch")

from backend.cli import market_growth_pilot as pilot


# Existing research invocations keep CPU execution unless CUDA is requested.
def test_device_defaults_to_cpu():
    args = pilot.parser().parse_args(
        [
            "--data-dir",
            "data",
            "--output",
            "out",
            "--asof",
            "2026-09-14",
            "--revision",
            "test",
        ]
    )
    assert args.device == "cpu"
    assert pilot.resolve_device(args.device) == torch.device("cpu")


# An explicit accelerator request must fail rather than fall back to CPU.
def test_unavailable_cuda_fails_closed(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(ValueError, match="CUDA requested but unavailable"):
        pilot.resolve_device("cuda")
    assert pilot.resolve_device("cpu") == torch.device("cpu")


# Available CUDA and invalid selectors are handled explicitly.
def test_available_cuda_and_invalid_device(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert pilot.resolve_device("cuda") == torch.device("cuda")
    with pytest.raises(ValueError, match="Device must"):
        pilot.resolve_device("automatic")


# Saved CPU tensors are independent snapshots rather than mutable model views.
def test_portable_checkpoint_is_an_independent_cpu_copy():
    model = pilot.return_network(8)
    saved = pilot.portable_state(model)
    first = next(iter(saved))
    expected = saved[first].clone()
    with torch.no_grad():
        next(model.parameters()).add_(1)
    assert all(t.device.type == "cpu" for t in saved.values())
    torch.testing.assert_close(saved[first], expected)
    assert not torch.equal(saved[first], next(model.parameters()))


# A real CUDA model can optimize and return finite portable predictions.
@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA runtime unavailable")
def test_cuda_forward_backward_and_cpu_output():
    torch.manual_seed(0)
    model = pilot.return_network(8).to(pilot.resolve_device("cuda"))
    x = torch.randn(32, 8, device="cuda")
    before = pilot.portable_state(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    loss = model(x).square().mean()
    loss.backward()
    assert all(torch.isfinite(p.grad).all() for p in model.parameters())
    optimizer.step()
    after = pilot.portable_state(model)
    assert any(not torch.equal(before[k], after[k]) for k in before)
    predicted = pilot.predict(model, x.cpu().numpy())
    assert predicted.shape == (32,)
    assert bool(torch.isfinite(torch.from_numpy(predicted)).all())
