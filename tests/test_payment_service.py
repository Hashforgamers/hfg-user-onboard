import hashlib
import hmac
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import services.payment_service as payment_service


class RazorpayWebhookTests(unittest.TestCase):
    def _signed_payload(self, body):
        payload = json.dumps(body).encode("utf-8")
        signature = hmac.new(
            b"test-webhook-secret", payload, hashlib.sha256
        ).hexdigest()
        return payload, signature

    @patch.object(payment_service, "PROVIDER", "razorpay")
    @patch.dict(os.environ, {"RAZORPAY_WEBHOOK_SECRET": "test-webhook-secret"})
    def test_webhook_uses_receipt_when_notes_is_a_list(self):
        payload, signature = self._signed_payload({
            "event": "payment.captured",
            "payload": {
                "payment": {"entity": {"id": "pay_1", "notes": []}},
                "order": {"entity": {"id": "order_1", "receipt": "registration-1", "notes": []}},
            },
        })

        self.assertEqual(
            payment_service.verify_webhook(payload, signature),
            (True, "registration-1", "succeeded"),
        )
        details = payment_service.verified_webhook_payment_details(payload, signature)
        self.assertEqual(details["registration_id"], "registration-1")
        self.assertEqual(details["order_id"], "order_1")

    @patch.object(payment_service, "PROVIDER", "razorpay")
    @patch.dict(os.environ, {"RAZORPAY_WEBHOOK_SECRET": "test-webhook-secret"})
    def test_webhook_rejects_a_signed_non_object_payload(self):
        payload, signature = self._signed_payload([])
        self.assertEqual(
            payment_service.verify_webhook(payload, signature),
            (False, None, "failed"),
        )


if __name__ == "__main__":
    unittest.main()
