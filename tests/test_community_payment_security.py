import os
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from services.payment_service import _rzp_fetch_tournament_payment, verify_tournament_payment


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class CommunityPaymentSecurityTests(unittest.TestCase):
    @patch("services.payment_service.PROVIDER", "mock")
    def test_mock_payment_cannot_settle_without_explicit_opt_in(self):
        with patch.dict(os.environ, {"PAYMENT_ALLOW_MOCK": "false"}, clear=False):
            with self.assertRaisesRegex(ValueError, "mock payment settlement is disabled"):
                verify_tournament_payment({}, 100, "INR")

    @patch("services.payment_service._razorpay_credentials", return_value=("key", "secret"))
    def test_provider_payment_must_belong_to_the_registration_order(self, _credentials):
        get = unittest.mock.Mock(side_effect=[
            _Response({
                "id": "pay_123",
                "order_id": "order_123",
                "status": "captured",
                "amount": 10000,
                "currency": "INR",
            }),
            _Response({
                "id": "order_123",
                "receipt": "ctr_someone_else",
                "notes": {"registration_id": "someone-else"},
                "amount": 10000,
                "currency": "INR",
            }),
        ])
        with patch.dict(sys.modules, {"requests": SimpleNamespace(get=get)}):
            with self.assertRaisesRegex(ValueError, "not bound to this registration"):
                _rzp_fetch_tournament_payment(
                    "pay_123",
                    100,
                    "INR",
                    "order_123",
                    expected_registration_id="target-registration",
                )
