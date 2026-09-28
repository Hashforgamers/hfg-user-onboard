import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, g
from controllers.user_controller import claim_drop_crate, user_blueprint


class DropCrateClaimTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(user_blueprint, url_prefix='/api')
        self.patches = [patch('controllers.user_controller.' + name) for name in
                        ('db', 'HashWallet', 'HashWalletTransaction', '_invalidate_user_microcache')]
        self.db, self.wallet_model, self.txn_model, self.invalidate = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.db.session.query.return_value.filter_by.return_value.first.return_value = SimpleNamespace(id=42, deleted_at=None)
        self.wallet = SimpleNamespace(balance=25)
        self.wallet_model.query.filter_by.return_value.with_for_update.return_value.first.return_value = self.wallet
        self.txn_model.query.filter_by.return_value.first.return_value = None

    def invoke(self, body=None, expired=False):
        with self.app.test_request_context(method='POST', json=body):
            g.auth_user_id = 42
            g.token_expired = expired
            return claim_drop_crate.__wrapped__()

    def test_fixed_reward_without_internal_token(self):
        response, status = self.invoke({})
        self.assertEqual(status, 200)
        self.assertEqual(response.json['credited_amount'], 10)
        self.assertEqual(response.json['new_balance'], 35)
        self.txn_model.assert_called_once_with(user_id=42, amount=10, type='drop_crate', reference_id='drop_crate:42')
        self.db.session.commit.assert_called_once()
        self.invalidate.assert_called_once()

    def test_prior_claim_is_not_credited_again(self):
        self.txn_model.query.filter_by.return_value.first.return_value = SimpleNamespace(reference_id='legacy-reference')
        response, status = self.invoke()
        self.assertEqual(status, 200)
        self.assertTrue(response.json['already_claimed'])
        self.assertEqual(response.json['credited_amount'], 0)
        self.assertEqual(self.wallet.balance, 25)
        self.db.session.add.assert_not_called()
        self.txn_model.query.filter_by.assert_called_once_with(user_id=42, type='drop_crate')

    def test_rejects_client_controlled_fields_and_non_objects(self):
        for body in ({'amount': 100}, {'user_id': 7}, {'reference_id': 'new'}, [], 'x', {'type': 'top-up'}):
            with self.subTest(body=body):
                _, status = self.invoke(body)
                self.assertEqual(status, 400)
        self.db.session.execute.assert_not_called()

    def test_missing_or_deleted_account(self):
        for user in (None, SimpleNamespace(deleted_at='deleted')):
            self.db.session.query.return_value.filter_by.return_value.first.return_value = user
            _, status = self.invoke()
            self.assertEqual(status, 404)
        self.db.session.add.assert_not_called()

    def test_write_failure_rolls_back(self):
        self.db.session.commit.side_effect = RuntimeError('private database details')
        response, status = self.invoke()
        self.assertEqual(status, 500)
        self.assertNotIn('private', str(response.json))
        self.db.session.rollback.assert_called_once()
        self.invalidate.assert_not_called()

    def test_expired_token_rejected_even_in_legacy_auth_mode(self):
        _, status = self.invoke(expired=True)
        self.assertEqual(status, 401)
        self.db.session.execute.assert_not_called()

    def test_route_requires_authentication(self):
        response = self.app.test_client().post('/api/users/wallet/drop-crate/claim', json={})
        self.assertEqual(response.status_code, 401)
        self.db.session.execute.assert_not_called()
