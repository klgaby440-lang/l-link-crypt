import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("THINK_SSO_SECRET", "test-sso-secret-" + ("x" * 48))
os.environ.setdefault("THINK_SERVICE_TOKEN", "test-service-token-" + ("y" * 48))

import pytest
from fastapi import HTTPException

from llink_api.services.credit_wallet import credits_for_microusd, daily_free_credit_amount


def test_credit_conversion_rounds_up_to_next_cent_credit():
    assert credits_for_microusd(1) == 1
    assert credits_for_microusd(10_000) == 1
    assert credits_for_microusd(10_001) == 2
    assert credits_for_microusd(0, minimum_one=False) == 0


def test_image_cost_equivalent_rounds_to_eleven_hd_credits():
    assert credits_for_microusd(101_000) == 11
    assert credits_for_microusd(67_000) == 7


def test_daily_free_credits_configuration_is_bounded(monkeypatch):
    monkeypatch.setenv("LLINK_DAILY_FREE_CREDITS", "12")
    assert daily_free_credit_amount() == 12
    monkeypatch.setenv("LLINK_DAILY_FREE_CREDITS", "1001")
    with pytest.raises(HTTPException):
        daily_free_credit_amount()
