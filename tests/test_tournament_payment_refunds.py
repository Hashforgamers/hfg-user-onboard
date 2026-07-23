import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.payment_service import refund_tournament_payment


def response(payload):
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)


class TournamentPaymentRefundTests(unittest.TestCase):
    @patch("services.payment_service.PROVIDER", "razorpay")
    @patch("services.payment_service._razorpay_credentials", return_value=("key", "secret"))
    @patch("requests.post")
    @patch("requests.get")
    def test_existing_pending_receipt_prevents_duplicate_refund(
        self,
        get,
        post,
        _credentials,
    ):
        get.return_value = response({
            "items": [{
                "id": "rfnd_existing",
                "payment_id": "pay_123",
                "amount": 25000,
                "currency": "INR",
                "status": "pending",
                "receipt": "ctr_registration",
            }],
        })

        result = refund_tournament_payment(
            "pay_123",
            "250.00",
            "INR",
            "ctr_registration",
            provider="razorpay",
        )

        self.assertEqual(result["refund_id"], "rfnd_existing")
        self.assertEqual(result["status"], "pending")
        post.assert_not_called()

    @patch("services.payment_service.PROVIDER", "razorpay")
    @patch("services.payment_service._razorpay_credentials", return_value=("key", "secret"))
    @patch("requests.post")
    @patch("requests.get")
    def test_creates_normal_refund_in_paise_with_stable_receipt(
        self,
        get,
        post,
        _credentials,
    ):
        get.return_value = response({"items": []})
        post.return_value = response({
            "id": "rfnd_new",
            "payment_id": "pay_123",
            "amount": 25000,
            "currency": "INR",
            "status": "processed",
            "receipt": "ctr_registration",
        })

        result = refund_tournament_payment(
            "pay_123",
            "250.00",
            "INR",
            "ctr_registration",
            provider="razorpay",
        )

        self.assertEqual(result["refund_id"], "rfnd_new")
        self.assertEqual(result["status"], "processed")
        post.assert_called_once_with(
            "https://api.razorpay.com/v1/payments/pay_123/refund",
            auth=("key", "secret"),
            json={
                "amount": 25000,
                "speed": "normal",
                "receipt": "ctr_registration",
                "notes": {"source": "community_tournament_registration"},
            },
            timeout=10,
        )

    @patch("services.payment_service.PROVIDER", "mock")
    def test_razorpay_registration_fails_closed_under_mock_configuration(self):
        with self.assertRaisesRegex(ValueError, "not configured"):
            refund_tournament_payment(
                "pay_123",
                "250.00",
                "INR",
                "ctr_registration",
                provider="razorpay",
            )


if __name__ == "__main__":
    unittest.main()
