import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from controllers.user_controller import (
    _sanitize_signup_payload,
    _validate_signup_payload,
    user_blueprint,
)
from models.user import User
from services.user_service import UserService


class UserSignupApiTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            USER_SIGNUP_EMAIL_RECOVERY_ENABLED=False,
            USER_CREATE_TIMING_LOGS=False,
        )
        self.app.register_blueprint(user_blueprint, url_prefix="/api")
        self.client = self.app.test_client()

    def test_rejects_non_object_json(self):
        response = self.client.post("/api/users", json=["not", "an", "object"])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["details"], "request body must be a JSON object")

    def test_signup_accepts_lowercase_address_keys(self):
        payload = _sanitize_signup_payload({
            "fid": "firebase-user-123",
            "gameUserName": "PlayerOne",
            "contact": {
                "physicalAddress": {"state": "Maharashtra", "country": "India"},
            },
        })

        self.assertEqual(payload["contact"]["physicalAddress"]["State"], "Maharashtra")
        self.assertEqual(payload["contact"]["physicalAddress"]["Country"], "India")

    def test_validates_contact_columns_before_database_insert(self):
        payload = _sanitize_signup_payload({
            "fid": "firebase-user-123",
            "gameUserName": "PlayerOne",
            "contact": {"electronicAddress": {"mobileNo": "1" * 51}},
        })

        self.assertEqual(_validate_signup_payload(payload), "mobileNo must be at most 50 characters")

    @patch("controllers.user_controller._merge_existing_user_by_email")
    @patch("controllers.user_controller.UserService.create_user")
    def test_email_recovery_is_disabled_by_default(self, create_user, merge_user):
        create_user.return_value = {
            "status": "error",
            "state": "EMAIL_EXISTS",
            "message": "This email is already in use.",
            "details": {"email": "player@example.com"},
        }

        response = self.client.post("/api/users", json={
            "fid": "firebase-user-123",
            "gameUserName": "PlayerOne",
            "contact": {"electronicAddress": {"emailId": "player@example.com"}},
        })

        self.assertEqual(response.status_code, 409)
        merge_user.assert_not_called()

    @patch("services.user_service.UserService.finalize_user_post_create")
    def test_async_finalization_submission_failure_falls_back_to_sync(self, finalize_user):
        with self.app.app_context(), patch(
            "services.user_service._USER_POST_CREATE_EXECUTOR.submit",
            side_effect=RuntimeError("executor shut down"),
        ):
            UserService.enqueue_post_create_finalize(1, "U1", app_obj=self.app)

        finalize_user.assert_called_once_with(
            user_id=1,
            own_referral_code="U1",
            referral_input=None,
        )

    def test_user_payload_includes_fid(self):
        user = User(fid="firebase-user-123", name="Player", game_username="PlayerOne")

        self.assertEqual(user.to_dict()["fid"], "firebase-user-123")


if __name__ == "__main__":
    unittest.main()
