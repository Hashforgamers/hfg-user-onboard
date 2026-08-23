import hashlib
import hmac
import os
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from services.payment_service import (
    _rzp_create_order,
    _rzp_fetch_tournament_payment,
    fetch_tournament_payment_for_order,
    verify_tournament_payment,
)


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

    @patch("services.payment_service._razorpay_credentials", return_value=("key", "secret"))
    def test_booking_receipt_can_bind_legacy_order_to_registration_user(self, _credentials):
        get = unittest.mock.Mock(side_effect=[
            _Response({
                "id": "pay_123",
                "order_id": "order_123",
                "status": "captured",
                "amount": 100,
                "currency": "INR",
            }),
            _Response({
                "id": "order_123",
                "receipt": "bk_638_abc",
                "notes": {"source": "hfg_booking"},
                "amount": 100,
                "currency": "INR",
            }),
        ])
        with patch.dict(sys.modules, {"requests": SimpleNamespace(get=get)}):
            result = _rzp_fetch_tournament_payment(
                "pay_123",
                1,
                "INR",
                "order_123",
                expected_registration_id="registration-1",
                expected_user_id=638,
            )

        self.assertEqual(result["payment_id"], "pay_123")
        self.assertEqual(result["status"], "captured")

    @patch("services.payment_service.PROVIDER", "razorpay")
    @patch("services.payment_service._razorpay_credentials", return_value=("key", "secret"))
    def test_verify_callback_accepts_legacy_booking_order_for_same_user(self, _credentials):
        signature = hmac.new(
            b"secret",
            b"order_123|pay_123",
            hashlib.sha256,
        ).hexdigest()
        get = unittest.mock.Mock(side_effect=[
            _Response({
                "id": "pay_123",
                "order_id": "order_123",
                "status": "captured",
                "amount": 100,
                "currency": "INR",
            }),
            _Response({
                "id": "order_123",
                "receipt": "bk_638_abc",
                "notes": {"source": "hfg_booking"},
                "amount": 100,
                "currency": "INR",
            }),
        ])

        with patch.dict(sys.modules, {"requests": SimpleNamespace(get=get)}):
            result = verify_tournament_payment(
                {
                    "razorpay_payment_id": "pay_123",
                    "razorpay_order_id": "order_123",
                    "razorpay_signature": signature,
                },
                1,
                "INR",
                expected_registration_id="registration-1",
                expected_order_id="order_123",
                expected_user_id=638,
            )

        self.assertEqual(result["payment_id"], "pay_123")
        self.assertEqual(result["status"], "captured")

    @patch.dict(os.environ, {"RAZORPAY_KEY_ID": "key", "RAZORPAY_KEY_SECRET": "secret"})
    def test_razorpay_order_requests_auto_capture(self):
        post = unittest.mock.Mock(return_value=_Response({
            "id": "order_123",
            "amount": 10000,
            "currency": "INR",
        }))
        with patch.dict(sys.modules, {"requests": SimpleNamespace(post=post)}):
            result = _rzp_create_order(
                100,
                "INR",
                {"registration_id": "registration-1", "receipt": "ctr_registration"},
            )

        self.assertEqual(result["order_id"], "order_123")
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["payment_capture"], 1)
        self.assertEqual(payload["notes"]["registration_id"], "registration-1")

    @patch("services.payment_service._razorpay_credentials", return_value=("key", "secret"))
    def test_authorized_payment_is_captured_before_settlement(self, _credentials):
        get = unittest.mock.Mock(side_effect=[
            _Response({
                "id": "pay_123",
                "order_id": "order_123",
                "status": "authorized",
                "amount": 10000,
                "currency": "INR",
            }),
            _Response({
                "id": "order_123",
                "receipt": "ctr_registration",
                "notes": {"registration_id": "registration-1"},
                "amount": 10000,
                "currency": "INR",
            }),
        ])
        post = unittest.mock.Mock(return_value=_Response({
            "id": "pay_123",
            "order_id": "order_123",
            "status": "captured",
            "amount": 10000,
            "currency": "INR",
        }))

        with patch.dict(sys.modules, {"requests": SimpleNamespace(get=get, post=post)}):
            result = _rzp_fetch_tournament_payment(
                "pay_123",
                100,
                "INR",
                "order_123",
                expected_registration_id="registration-1",
            )

        self.assertEqual(result["status"], "captured")
        post.assert_called_once_with(
            "https://api.razorpay.com/v1/payments/pay_123/capture",
            auth=("key", "secret"),
            json={"amount": 10000, "currency": "INR"},
            timeout=10,
        )

    @patch("services.payment_service.PROVIDER", "razorpay")
    @patch("services.payment_service._razorpay_credentials", return_value=("key", "secret"))
    def test_order_reconciliation_finds_captured_payment(self, _credentials):
        get = unittest.mock.Mock(side_effect=[
            _Response({
                "items": [{
                    "id": "pay_123",
                    "order_id": "order_123",
                    "status": "captured",
                    "amount": 100,
                    "currency": "INR",
                }],
            }),
            _Response({
                "id": "pay_123",
                "order_id": "order_123",
                "status": "captured",
                "amount": 100,
                "currency": "INR",
            }),
            _Response({
                "id": "order_123",
                "receipt": "bk_638_abc",
                "notes": {"source": "hfg_booking", "user_id": "638"},
                "amount": 100,
                "currency": "INR",
            }),
        ])

        with patch.dict(sys.modules, {"requests": SimpleNamespace(get=get)}):
            result = fetch_tournament_payment_for_order(
                "order_123",
                1,
                "INR",
                expected_registration_id="registration-1",
                expected_user_id=638,
            )

        self.assertEqual(result["payment_id"], "pay_123")
        self.assertEqual(result["status"], "captured")
        self.assertEqual(get.call_args_list[0].args[0], "https://api.razorpay.com/v1/orders/order_123/payments")
