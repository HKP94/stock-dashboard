from __future__ import annotations

import time

import pytest

from src.external_timeout import ExternalCallTimeout, run_with_timeout


def test_run_with_timeout_returns_result_before_deadline() -> None:
    assert run_with_timeout(0.5, lambda: "ok") == "ok"


def test_run_with_timeout_raises_on_deadline_exceeded() -> None:
    with pytest.raises(ExternalCallTimeout):
        run_with_timeout(0.05, lambda: time.sleep(0.2))
