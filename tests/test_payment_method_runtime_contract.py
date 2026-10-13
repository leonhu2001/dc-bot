from __future__ import annotations

import inspect

from services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD
from services import order_runtime
from services import order_payment_runtime


def test_wallet_payment_method_is_canonical_and_available_without_runtime_injection():
    assert WALLET_PAYMENT_METHOD == "我的錢包"
    assert WALLET_PAYMENT_METHOD in PAYMENT_METHOD_OPTIONS
    assert order_runtime.WALLET_PAYMENT_METHOD == WALLET_PAYMENT_METHOD
    assert order_payment_runtime.WALLET_PAYMENT_METHOD == WALLET_PAYMENT_METHOD


def test_payment_runtime_configuration_no_longer_requires_wallet_label_injection():
    parameters = inspect.signature(order_payment_runtime.configure_order_payment_runtime).parameters
    assert "wallet_payment_method" not in parameters


def test_order_runtime_uses_canonical_payment_constants():
    source = inspect.getsource(order_runtime)
    assert "from services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD" in source
    assert 'wallet_payment_method=namespace["WALLET_PAYMENT_METHOD"]' not in source
