"""Pin the legacy allocation loss's cancelled gradient without training a policy.

The exact-source Torch diagnosis is retained at
/private/tmp/anios-legacy-pg-gradient.ZBn27B/RECEIPT.md (SHA256
1f3cc06208435904d1295febb3123048831443e268bc3a0272e27c998bca5116).
For p=softmax(z), w=G*p and detached advantage A, the current loss has
dL/dz_j=-A*(w_j-p_j*sum(w))=0. Floating-point residuals can still move Adam;
these tests do not claim historical parameters were unchanged.

Only the actual weight/loss AST is executed, with fixed synthetic inputs.
No application import, optimizer, training episode or historical data is used.
The Gaussian score-function reference is diagnostic, not a corrected strategy.
"""

import ast
import hashlib
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "cli" / "market_allocation_rl.py"
EXPECTED_ASSIGNMENTS = {
    "noisy": "noisy = scores + torch.randn_like(scores) * NOISE",
    "w": "w = _weights(noisy, gross)",
    "reward": "reward = _reward(problem, w.detach().cpu().numpy(), t)",
    "baseline": "baseline = 0.9 * baseline + 0.1 * reward",
    "logp": "logp = torch.log_softmax(noisy, dim=-1)",
    "loss": "loss = -(logp * w.detach()).sum() * (reward - baseline)",
}
BROKEN_GRADIENT = (
    "Confirmed legacy PG defect: current detached softmax weights cancel the "
    "log-softmax gradient; exact-source Torch proof "
    "anios-legacy-pg-gradient.ZBn27B/RECEIPT.md, SHA256 "
    "1f3cc06208435904d1295febb3123048831443e268bc3a0272e27c998bca5116. "
    "No learner correction or historical rerun is authorized by this regression."
)


# Reject extraction drift with an error the numerical expected failures cannot hide.
def _require_shape(condition, message):
    if not condition:
        raise RuntimeError(f"Legacy objective extraction requires review: {message}")


# Find exactly one top-level assignment to the requested local variable.
def _assignment(statements, name):
    matches = [
        node
        for node in statements
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    ]
    _require_shape(len(matches) == 1, f"expected one assignment to {name}")
    return matches[0]


# Compare source syntax while ignoring comments, whitespace and line numbers.
def _syntax(node):
    _require_shape(isinstance(node, ast.AST), "expected an AST node")
    return ast.dump(node, include_attributes=False)


# Validate the live inline objective and compile only its actual source expressions.
def _extract_objective(source):
    try:
        tree = ast.parse(source, filename=str(SOURCE))
    except SyntaxError as exc:
        raise RuntimeError("Legacy objective source no longer parses") from exc
    definitions = {}
    for name in ("_weights", "_policy_gradient"):
        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ]
        _require_shape(len(matches) == 1, f"expected one {name} function")
        definitions[name] = matches[0]
    weights = definitions["_weights"]
    weight_body = [
        node
        for node in weights.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    expected_weights = ast.parse(
        "def _weights(scores: torch.Tensor, gross: float) -> torch.Tensor:\n"
        "    return torch.softmax(scores, dim=-1) * gross\n"
    ).body[0]
    _require_shape(
        len(weight_body) == 1
        and _syntax(weight_body[0]) == _syntax(expected_weights.body[0]),
        "weight calculation changed",
    )
    _require_shape(
        _syntax(weights.args) == _syntax(expected_weights.args)
        and _syntax(weights.returns) == _syntax(expected_weights.returns)
        and not weights.decorator_list,
        "weight function interface changed",
    )
    loops = [
        node
        for node in definitions["_policy_gradient"].body
        if isinstance(node, ast.For)
    ]
    _require_shape(len(loops) == 1, "expected one episode loop")
    selected = {}
    for name, expected in EXPECTED_ASSIGNMENTS.items():
        node = _assignment(loops[0].body, name)
        _require_shape(
            _syntax(node) == _syntax(ast.parse(expected).body[0]),
            f"{name} expression changed",
        )
        selected[name] = node
    positions = [loops[0].body.index(node) for node in selected.values()]
    _require_shape(
        positions == list(range(positions[0], positions[0] + len(selected))),
        "objective statements are no longer contiguous and ordered",
    )
    expected_tail = ast.parse("opt.zero_grad()\nloss.backward()\nopt.step()\n")
    actual_tail = ast.Module(body=loops[0].body[positions[-1] + 1 :], type_ignores=[])
    _require_shape(
        _syntax(actual_tail) == _syntax(expected_tail),
        "objective-to-backward boundary changed",
    )
    noise = _assignment(tree.body, "NOISE").value
    _require_shape(
        isinstance(noise, ast.Constant)
        and type(noise.value) is float
        and noise.value == 0.3,
        "exploration scale changed",
    )
    actual_loss = ast.Module(
        body=[selected[name] for name in ("w", "baseline", "logp", "loss")],
        type_ignores=[],
    )
    return (
        compile(ast.Module(body=[weights], type_ignores=[]), str(SOURCE), "exec"),
        compile(actual_loss, str(SOURCE), "exec"),
        noise.value,
    )


# Retain this run's source identity without making harmless comments a permanent pin.
@pytest.fixture
def source_objective(record_property):
    source = SOURCE.read_bytes()
    record_property(
        "legacy_objective_source_sha256", hashlib.sha256(source).hexdigest()
    )
    record_property("legacy_objective_mode", "exact-source-AST-no-training")
    return _extract_objective(source)


# Require real Torch only for autograd cases, never for source-shape checks.
@pytest.fixture
def torch_runtime(record_property):
    torch = pytest.importorskip("torch")
    record_property("torch_version", torch.__version__)
    record_property("gradient_device", "cpu")
    return torch


# Supply fixed scores and exploration noise without sampling or reading market data.
def _inputs(torch, precision, shape):
    dtype = getattr(torch, precision)
    noise = torch.tensor([0.1, -0.2, 0.05, 0.3], dtype=dtype, device="cpu")
    if shape == "uniform":
        return -noise, noise, 0.5
    return (
        torch.tensor([0.2, -0.4, 1.1, -0.8], dtype=dtype, device="cpu"),
        noise,
        0.7,
    )


# Differentiate the source-extracted loss while keeping its reward outside autograd.
def _actual_gradient(torch, objective, precision, shape, reward):
    weights_code, loss_code, _noise_scale = objective
    initial, noise, gross = _inputs(torch, precision, shape)
    scores = initial.clone().requires_grad_(True)
    namespace = {"torch": torch}
    exec(weights_code, namespace)
    namespace.update(noisy=scores + noise, gross=gross, reward=reward, baseline=0.0)
    exec(loss_code, namespace)
    gradient = torch.autograd.grad(namespace["loss"], scores)[0]
    return gradient, reward - namespace["baseline"], noise


# Differentiate a stated Gaussian score-function estimator for the fixed sampled logits.
def _reference_gradient(torch, precision, shape, advantage, noise_scale):
    initial, noise, _gross = _inputs(torch, precision, shape)
    scores = initial.clone().requires_grad_(True)
    sampled_logits = (scores + noise).detach()
    distribution = torch.distributions.Normal(scores, noise_scale)
    loss = -advantage * distribution.log_prob(sampled_logits).sum()
    return torch.autograd.grad(loss, scores)[0], -advantage * noise / noise_scale**2


# Keep extraction validation a normal test even while the gradient defect is expected.
def test_actual_inline_objective_matches_the_extraction_contract(source_objective):
    assert source_objective[2] == 0.3


# Reject objective syntax changes outside the numerical AssertionError xfails.
@pytest.mark.parametrize("name", ["w", "reward", "loss"])
def test_changed_objective_is_an_explicit_extraction_error(name):
    source = SOURCE.read_text(encoding="utf-8")
    original = EXPECTED_ASSIGNMENTS[name]
    _require_shape(source.count(original) == 1, "mutation control target changed")
    changed = source.replace(original, f"{name} = None", 1)
    with pytest.raises(RuntimeError, match="extraction requires review"):
        _extract_objective(changed)


# Mutations between objective statements or before backward must not escape extraction.
@pytest.mark.parametrize("after", ["w", "loss"])
def test_inserted_objective_mutation_is_an_explicit_extraction_error(after):
    source = SOURCE.read_text(encoding="utf-8")
    original = EXPECTED_ASSIGNMENTS[after]
    _require_shape(source.count(original) == 1, "insertion control target changed")
    changed = source.replace(original, original + "\n        w.add_(1.0)", 1)
    with pytest.raises(RuntimeError, match="extraction requires review"):
        _extract_objective(changed)


# Comments and whitespace must not masquerade as changes to the objective's meaning.
def test_harmless_comment_does_not_invalidate_extraction():
    source = SOURCE.read_text(encoding="utf-8")
    _extract_objective("# An unrelated explanatory comment.\n\n" + source)


# A zero advantage must exert no policy pressure under the actual legacy expression.
@pytest.mark.parametrize("precision", ["float32", "float64"])
@pytest.mark.parametrize("shape", ["uniform", "asymmetric"])
def test_zero_advantage_has_zero_actual_gradient(
    torch_runtime, source_objective, precision, shape
):
    gradient, advantage, _noise = _actual_gradient(
        torch_runtime, source_objective, precision, shape, 0.0
    )
    assert advantage == 0.0
    assert torch_runtime.count_nonzero(gradient).item() == 0


# Check the diagnostic Gaussian estimator against its independent analytical derivative.
@pytest.mark.parametrize("precision", ["float32", "float64"])
@pytest.mark.parametrize("shape", ["uniform", "asymmetric"])
@pytest.mark.parametrize("advantage", [-1.8, 0.0, 1.8])
def test_gaussian_reference_has_the_declared_reward_direction(
    torch_runtime, source_objective, precision, shape, advantage
):
    gradient, expected = _reference_gradient(
        torch_runtime, precision, shape, advantage, source_objective[2]
    )
    tolerance = 100 * torch_runtime.finfo(gradient.dtype).eps
    assert torch_runtime.allclose(gradient, expected, atol=tolerance, rtol=tolerance)
    if advantage:
        assert gradient.abs().max().item() > 1.0
    else:
        assert torch_runtime.count_nonzero(gradient).item() == 0


# Preserve the broken reward-directed gradient as a strict numerical known failure.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=BROKEN_GRADIENT)
@pytest.mark.parametrize("precision", ["float32", "float64"])
@pytest.mark.parametrize("shape", ["uniform", "asymmetric"])
@pytest.mark.parametrize("reward", [-2.0, 2.0])
def test_legacy_gradient_matches_its_gaussian_exploration_score(
    torch_runtime, source_objective, precision, shape, reward
):
    gradient, advantage, noise = _actual_gradient(
        torch_runtime, source_objective, precision, shape, reward
    )
    expected = -advantage * noise / source_objective[2] ** 2
    tolerance = 100 * torch_runtime.finfo(gradient.dtype).eps
    assert torch_runtime.allclose(gradient, expected, atol=tolerance, rtol=tolerance), (
        f"legacy gradient {gradient.tolist()} cancels despite advantage {advantage}; "
        f"Gaussian score-function expectation is {expected.tolist()}"
    )
