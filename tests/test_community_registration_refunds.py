import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from models.communityTournament import CommunityTournamentRegistrationStatus
from services.community_tournament_service import (
    CommunityConflictError,
    _refund_or_cancel_registration,
)


def registration(**overrides):
    values = {
        "id": uuid.uuid4(),
        "user_id": 42,
        "status": CommunityTournamentRegistrationStatus.CONFIRMED,
        "payment_status": "paid",
        "amount_paid": Decimal("250.00"),
        "payment_provider": "razorpay",
        "razorpay_payment_id": "pay_123",
        "razorpay_refund_id": None,
        "refund_amount": Decimal("0"),
        "refund_status": None,
        "refund_requested_at": None,
        "refunded_at": None,
        "refund_error": None,
        "cancelled_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def tournament(count=3):
    return SimpleNamespace(
        id=uuid.uuid4(),
        currency="INR",
        entry_fee=Decimal("250.00"),
        registered_players_count=count,
        total_collection=Decimal("750.00"),
        platform_fee_amount=Decimal("0"),
        organizer_commission_rate=Decimal("8"),
        organizer_commission_amount=Decimal("0"),
        prize_pool=Decimal("0"),
        prize_distribution=[],
    )


class CommunityRegistrationRefundTests(unittest.TestCase):
    @patch("services.payment_service.refund_tournament_payment")
    def test_processed_razorpay_refund_is_persisted_without_wallet_credit(self, refund_payment):
        reg = registration()
        event = tournament()
        refund_payment.return_value = {
            "refund_id": "rfnd_123",
            "amount": Decimal("250.00"),
            "status": "processed",
        }

        with patch("services.community_tournament_service._apply_wallet_transaction") as wallet_credit:
            _refund_or_cancel_registration(reg, event)

        self.assertEqual(reg.status, CommunityTournamentRegistrationStatus.REFUNDED)
        self.assertEqual(reg.payment_status, "refunded")
        self.assertEqual(reg.razorpay_refund_id, "rfnd_123")
        self.assertEqual(event.registered_players_count, 2)
        wallet_credit.assert_not_called()
        refund_payment.assert_called_once()

    @patch("services.payment_service.refund_tournament_payment")
    def test_pending_refund_reconciles_without_second_count_decrement(self, refund_payment):
        reg = registration()
        event = tournament()
        refund_payment.side_effect = [
            {
                "refund_id": "rfnd_pending",
                "amount": Decimal("250.00"),
                "status": "pending",
            },
            {
                "refund_id": "rfnd_pending",
                "amount": Decimal("250.00"),
                "status": "processed",
            },
        ]

        _refund_or_cancel_registration(reg, event)

        self.assertEqual(reg.status, CommunityTournamentRegistrationStatus.REFUND_PENDING)
        self.assertEqual(event.registered_players_count, 2)

        _refund_or_cancel_registration(reg, event)

        self.assertEqual(reg.status, CommunityTournamentRegistrationStatus.REFUNDED)
        self.assertEqual(event.registered_players_count, 2)
        self.assertEqual(refund_payment.call_count, 2)
        self.assertEqual(
            refund_payment.call_args.kwargs["existing_refund_id"],
            "rfnd_pending",
        )

    @patch("services.payment_service.refund_tournament_payment", side_effect=RuntimeError("provider unavailable"))
    def test_provider_failure_leaves_registration_and_count_active(self, _refund_payment):
        reg = registration()
        event = tournament()

        with self.assertRaisesRegex(CommunityConflictError, "registration remains active"):
            _refund_or_cancel_registration(reg, event)

        self.assertEqual(reg.status, CommunityTournamentRegistrationStatus.CONFIRMED)
        self.assertEqual(reg.payment_status, "paid")
        self.assertEqual(event.registered_players_count, 3)

    def test_unpaid_pending_cancellation_does_not_decrement_confirmed_count(self):
        reg = registration(
            status=CommunityTournamentRegistrationStatus.PENDING_PAYMENT,
            payment_status="unpaid",
            amount_paid=Decimal("0"),
            payment_provider=None,
            razorpay_payment_id=None,
        )
        event = tournament()

        _refund_or_cancel_registration(reg, event)

        self.assertEqual(reg.status, CommunityTournamentRegistrationStatus.CANCELLED)
        self.assertEqual(event.registered_players_count, 3)

    @patch("services.community_tournament_service._apply_wallet_transaction")
    def test_legacy_wallet_refund_remains_supported(self, wallet_credit):
        reg = registration(payment_provider="wallet", razorpay_payment_id=None)
        event = tournament()

        _refund_or_cancel_registration(reg, event)

        self.assertEqual(reg.status, CommunityTournamentRegistrationStatus.REFUNDED)
        self.assertEqual(reg.payment_status, "refunded")
        self.assertEqual(event.registered_players_count, 2)
        wallet_credit.assert_called_once_with(
            reg.user_id,
            reg.amount_paid,
            "community-tournament-refund",
            event.id,
        )

    def test_unknown_paid_provider_fails_closed(self):
        reg = registration(payment_provider="unknown")
        event = tournament()

        with self.assertRaisesRegex(CommunityConflictError, "supported refund provider"):
            _refund_or_cancel_registration(reg, event)

        self.assertEqual(reg.status, CommunityTournamentRegistrationStatus.CONFIRMED)
        self.assertEqual(event.registered_players_count, 3)


if __name__ == "__main__":
    unittest.main()
