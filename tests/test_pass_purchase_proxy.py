"""Compatibility contract for the read-only Flutter app's purchase endpoint."""
import ast
import os
from pathlib import Path
from unittest.mock import Mock, patch
import unittest
from flask import Flask, current_app, g, jsonify, request
import requests


class PassPurchaseProxyTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config['BOOKING_SERVICE_URL'] = 'https://booking.test'
        self.invalidate = Mock()
        scope = dict(globals(), _invalidate_user_microcache=self.invalidate)
        source = Path(__file__).resolve().parents[1] / 'controllers/user_controller.py'
        node = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'user_purchase_pass')
        node.decorator_list = []
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
        app.add_url_rule('/api/user/purchase_pass', view_func=scope['user_purchase_pass'], methods=['POST'])
        app.before_request(lambda: setattr(g, 'auth_user_id', 1))
        self.client = app.test_client()
        self.payload = {'cafe_pass_id': '1', 'payment_id': 'pay_legacy_1', 'payment_mode': 'gateway'}

    @patch('requests.post')
    def test_new_purchase_and_retry_return_flutter_success_contract(self, post):
        for status in (201, 200):
            post.return_value = Mock(status_code=status, json=lambda: {'success': True, 'transaction_id': 10})
            response = self.client.post('/api/user/purchase_pass', json=self.payload, headers={'Authorization': 'Bearer test'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['message'], 'Pass purchased successfully')
            self.assertEqual(post.call_args.args[0], 'https://booking.test/api/user/passes/purchase')
            self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer test')
            self.assertEqual(post.call_args.kwargs['json'], self.payload)
        self.assertEqual(self.invalidate.call_count, 2)

    @patch('requests.post')
    def test_verification_failure_is_not_reported_as_success(self, post):
        post.return_value = Mock(status_code=403, json=lambda: {'error': 'Payment belongs to another user'})
        response = self.client.post('/api/user/purchase_pass', json=self.payload)
        self.assertEqual(response.status_code, 403)
        self.invalidate.assert_not_called()

    @patch('requests.post', side_effect=requests.Timeout)
    def test_timeout_preserves_retry_path(self, post):
        response = self.client.post('/api/user/purchase_pass', json=self.payload)
        self.assertEqual(response.status_code, 502)
        self.assertIn('same payment', response.json['message'])

    @patch('requests.post')
    def test_invalid_body_never_calls_purchase_service(self, post):
        self.assertEqual(self.client.post('/api/user/purchase_pass', json=[]).status_code, 400)
        post.assert_not_called()
