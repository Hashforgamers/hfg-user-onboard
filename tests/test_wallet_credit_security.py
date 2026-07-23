import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, g

from controllers.user_controller import add_wallet_balance


class WalletCreditSecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            WALLET_CREDIT_INTERNAL_TOKEN="internal-test-token",
            WALLET_CREDIT_MAX_AMOUNT=1000,
        )
        self.handler = add_wallet_balance.__wrapped__

    def invoke(self, body=None, token=None):
        headers = {}
        if token is not None:
            headers["X-Wallet-Credit-Token"] = token
        with self.app.test_request_context(
            "/api/users/wallet",
            method="POST",
            json=body,
            headers=headers,
        ):
            g.auth_user_id = 42
            return self.handler()

    @patch("controllers.user_controller.HashWallet")
    def test_rejects_authenticated_user_without_internal_token(self, wallet_model):
        response, status = self.invoke({"amount": 100, "reference_id": "payment-1"})

        self.assertEqual(status, 403)
        self.assertEqual(response.get_json()["message"], "Wallet credit authorization required")
        wallet_model.query.filter_by.assert_not_called()

    @patch("controllers.user_controller.HashWallet")
    def test_rejects_wrong_internal_token(self, wallet_model):
        response, status = self.invoke(
            {"amount": 100, "reference_id": "payment-1"},
            token="wrong-token",
        )

        self.assertEqual(status, 403)
        wallet_model.query.filter_by.assert_not_called()

    @patch("controllers.user_controller.HashWallet")
    def test_fails_closed_when_internal_token_is_not_configured(self, wallet_model):
        self.app.config["WALLET_CREDIT_INTERNAL_TOKEN"] = ""

        response, status = self.invoke({"amount": 100, "reference_id": "payment-1"})

        self.assertEqual(status, 503)
        wallet_model.query.filter_by.assert_not_called()

    @patch("controllers.user_controller.HashWallet")
    def test_requires_idempotency_reference_before_wallet_access(self, wallet_model):
        response, status = self.invoke({"amount": 100}, token="internal-test-token")

        self.assertEqual(status, 400)
        self.assertEqual(response.get_json()["message"], "reference_id is required")
        wallet_model.query.filter_by.assert_not_called()

    @patch("controllers.user_controller.HashWallet")
    def test_rejects_amount_above_configured_limit_before_wallet_access(self, wallet_model):
        response, status = self.invoke(
            {"amount": 1001, "reference_id": "payment-1"},
            token="internal-test-token",
        )

        self.assertEqual(status, 400)
        wallet_model.query.filter_by.assert_not_called()

    @patch("controllers.user_controller.notify_user_all_tokens")
    @patch("controllers.user_controller._invalidate_user_microcache")
    @patch("controllers.user_controller.db")
    @patch("controllers.user_controller.HashWalletTransaction")
    @patch("controllers.user_controller.HashWallet")
    def test_authorized_credit_preserves_success_contract(
        self,
        wallet_model,
        transaction_model,
        mocked_db,
        invalidate_cache,
        notify_user,
    ):
        wallet = SimpleNamespace(balance=25)
        wallet_model.query.filter_by.return_value.with_for_update.return_value.first.return_value = wallet
        transaction_model.query.filter_by.return_value.first.return_value = None
        mocked_db.session.query.return_value.filter_by.return_value.first.return_value = SimpleNamespace(id=42)

        response = self.invoke(
            {"amount": 75, "type": "top-up", "reference_id": "payment-1"},
            token="internal-test-token",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"message": "Wallet updated", "new_balance": 100})
        transaction_model.assert_called_once_with(
            user_id=42,
            amount=75,
            type="top-up",
            reference_id="payment-1",
        )
        mocked_db.session.add.assert_called_once()
        mocked_db.session.commit.assert_called_once()
        notify_user.assert_called_once()
        invalidate_cache.assert_called_once()

    @patch("controllers.user_controller.notify_user_all_tokens")
    @patch("controllers.user_controller.db")
    @patch("controllers.user_controller.HashWalletTransaction")
    @patch("controllers.user_controller.HashWallet")
    def test_duplicate_reference_is_idempotent(
        self,
        wallet_model,
        transaction_model,
        mocked_db,
        notify_user,
    ):
        wallet = SimpleNamespace(balance=100)
        wallet_model.query.filter_by.return_value.with_for_update.return_value.first.return_value = wallet
        transaction_model.query.filter_by.return_value.first.return_value = SimpleNamespace(
            user_id=42,
            amount=75,
            type="top-up",
        )
        mocked_db.session.query.return_value.filter_by.return_value.first.return_value = SimpleNamespace(id=42)

        response, status = self.invoke(
            {"amount": 75, "type": "top-up", "reference_id": "payment-1"},
            token="internal-test-token",
        )

        self.assertEqual(status, 200)
        self.assertEqual(response.get_json()["new_balance"], 100)
        self.assertTrue(response.get_json()["idempotent"])
        mocked_db.session.add.assert_not_called()
        mocked_db.session.commit.assert_not_called()
        notify_user.assert_not_called()

    @patch("controllers.user_controller.db")
    @patch("controllers.user_controller.HashWalletTransaction")
    @patch("controllers.user_controller.HashWallet")
    def test_reference_cannot_be_reused_for_another_wallet(
        self,
        wallet_model,
        transaction_model,
        mocked_db,
    ):
        wallet_model.query.filter_by.return_value.with_for_update.return_value.first.return_value = SimpleNamespace(balance=25)
        transaction_model.query.filter_by.return_value.first.return_value = SimpleNamespace(
            user_id=7,
            amount=75,
            type="top-up",
        )
        mocked_db.session.query.return_value.filter_by.return_value.first.return_value = SimpleNamespace(id=42)

        response, status = self.invoke(
            {"amount": 75, "type": "top-up", "reference_id": "payment-1"},
            token="internal-test-token",
        )

        self.assertEqual(status, 409)
        self.assertEqual(
            response.get_json()["message"],
            "reference_id was already used for another wallet credit",
        )
        mocked_db.session.add.assert_not_called()
        mocked_db.session.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
