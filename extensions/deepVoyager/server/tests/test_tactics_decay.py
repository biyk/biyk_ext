# tests/test_tactics_decay.py — λ(iter) затухает монотонно к floor (§1.3, §7).
import pytest

from arent.tactics import decay_linear
from arent.tactics_config import parse


def test_lambda_endpoints_and_monotone():
    assert decay_linear(0, 60) == pytest.approx(1.0)
    assert decay_linear(60, 60) == pytest.approx(0.0)
    seq = [decay_linear(i, 60) for i in range(61)]
    assert all(seq[i] >= seq[i + 1] - 1e-12 for i in range(60))     # невозрастающая


def test_lambda_respects_floor():
    assert decay_linear(60, 60, floor=0.2) == pytest.approx(0.2)


def test_lambda_no_division_by_zero():
    assert decay_linear(3, 0) == pytest.approx(1.0)


def test_config_lambda_uses_mode_and_floor():
    cfg = parse({"decay": {"mode": "linear", "floor": 0.1}})
    assert cfg.lam(0, 100) == pytest.approx(1.0)
    assert cfg.lam(100, 100) == pytest.approx(0.1)
