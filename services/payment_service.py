import os
import hmac
import hashlib
import json
import logging
import time
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple, Dict, Any

PROVIDER = os.getenv("PAYMENT_PROVIDER", "mock").lower()    # "mock" | "razorpay" | "stripe"
CURRENCY_DEFAULT = os.getenv("PAYMENT_CURRENCY", "INR")
logger = logging.getLogger(__name__)


def _as_dict(value) -> Dict[str, Any]:
    """Provider webhooks are untrusted JSON; only mappings support metadata lookup."""
    return value if isinstance(value, dict) else {}


def _razorpay_entity(payload_data, entity_name: str) -> Dict[str, Any]:
    return _as_dict(_as_dict(_as_dict(payload_data).get(entity_name)).get("entity"))


def _razorpay_notes(entity) -> Dict[str, Any]:
    return _as_dict(_as_dict(entity).get("notes"))


def _razorpay_order_bound_to_user(order, payment, expected_user_id) -> bool:
    if not expected_user_id:
        return False
    expected_user_id = str(expected_user_id)
    notes_user_id = str(_razorpay_notes(order).get("user_id") or _razorpay_notes(payment).get("user_id") or "")
    receipt = str(_as_dict(order).get("receipt") or "")
    return notes_user_id == expected_user_id or bool(re.match(rf"^bk_{re.escape(expected_user_id)}_", receipt))


def _short(value, keep=8):
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= keep * 2:
        return value
    return f"{value[:keep]}...{value[-keep:]}"


def _raise_for_razorpay_status(response, context: str):
    try:
        response.raise_for_status()
    except Exception as exc:
        detail = ""
        try:
            payload = response.json()
            detail = json.dumps(payload, separators=(",", ":"), sort_keys=True)[:500]
        except Exception:
            detail = str(getattr(response, "text", "") or "")[:500]
        logger.warning(
            "razorpay_http_error context=%s status_code=%s response=%s",
            context,
            getattr(response, "status_code", None),
            detail,
        )
        raise ValueError(f"{context}: {exc}; response={detail}") from exc


def _mock_payments_allowed() -> bool:
    """Mock settlement is opt-in so an unset production provider cannot credit money."""
    return os.getenv("PAYMENT_ALLOW_MOCK", "false").lower() in {"1", "true", "yes"}

# ---------------------------
# Public interface
# ---------------------------

def create_payment_intent(amount: float, currency: str = None, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Creates a client-facing payment intent/order.
    Returns a dict the client can use to complete payment.
    """
    currency = currency or CURRENCY_DEFAULT
    metadata = metadata or {}
    if PROVIDER == "razorpay":
        return _rzp_create_order(amount, currency, metadata)
    elif PROVIDER == "stripe":
        return _stripe_create_intent(amount, currency, metadata)
    else:
        return _mock_create_intent(amount, currency, metadata)

def verify_webhook(payload: bytes, signature: str) -> Tuple[bool, str, str]:
    """
    Verifies webhook payload authenticity.
    Returns (ok, registration_id, status), where status is "succeeded" | "failed".
    """
    if PROVIDER == "razorpay":
        return _rzp_verify_webhook(payload, signature)
    elif PROVIDER == "stripe":
        return _stripe_verify_webhook(payload, signature)
    else:
        return _mock_verify_webhook(payload, signature)


def verified_webhook_payment_details(payload: bytes, signature: str) -> Dict[str, Any]:
    """Parse a provider-authenticated webhook into settlement details."""
    ok, registration_id, status = verify_webhook(payload, signature)
    if not ok:
        raise ValueError("invalid payment webhook signature")
    if PROVIDER != "razorpay":
        return {"registration_id": registration_id, "status": "captured" if status == "succeeded" else "failed"}
    event = _as_dict(json.loads(payload.decode("utf-8")))
    if not event:
        raise ValueError("invalid Razorpay webhook payload")
    payload_data = _as_dict(event.get("payload"))
    payment = _razorpay_entity(payload_data, "payment")
    order = _razorpay_entity(payload_data, "order")
    return {
        "registration_id": registration_id,
        "provider": "razorpay",
        "payment_id": str(payment.get("id") or "") or None,
        "order_id": str(payment.get("order_id") or order.get("id") or "") or None,
        "amount": Decimal(str(payment.get("amount") or 0)) / Decimal("100"),
        "currency": str(payment.get("currency") or order.get("currency") or "").upper(),
        "status": "captured" if status == "succeeded" else "failed",
        "event_type": str(event.get("event") or "unknown"),
    }


def verify_payment_success(data: Dict[str, Any]) -> Tuple[bool, str, str]:
    """
    Verifies a client-side payment success callback.
    Returns (ok, registration_id, status), where status is "succeeded" | "failed".
    """
    if PROVIDER == "razorpay":
        return _rzp_verify_payment_success(data)
    elif PROVIDER == "stripe":
        return False, None, "failed"
    else:
        reg_id = str(data.get("registration_id") or data.get("team_id") or "")
        return bool(reg_id), reg_id, "succeeded" if reg_id else "failed"


def verify_tournament_payment(
    data: Dict[str, Any],
    expected_amount,
    expected_currency: str,
    expected_registration_id: str = None,
    expected_order_id: str = None,
    expected_user_id: str = None,
) -> Dict[str, Any]:
    """Return provider-verified payment details for one tournament registration.

    This validates the client callback and then verifies the provider-side payment
    record. It intentionally does not mutate database state; settlement remains
    the responsibility of the community tournament transaction.
    """
    if PROVIDER == "razorpay":
        return _rzp_verify_tournament_payment(
            data,
            expected_amount,
            expected_currency,
            expected_registration_id=expected_registration_id,
            expected_order_id=expected_order_id,
            expected_user_id=expected_user_id,
        )
    if PROVIDER == "mock":
        if not _mock_payments_allowed():
            raise ValueError("mock payment settlement is disabled")
        payment_id = str(data.get("razorpay_payment_id") or data.get("payment_id") or data.get("payment_reference") or "mock-payment")
        order_id = str(data.get("razorpay_order_id") or data.get("order_id") or "mock-order")
        return {
            "provider": "mock",
            "payment_id": payment_id,
            "order_id": order_id,
            "amount": Decimal(str(expected_amount)).quantize(Decimal("0.01")),
            "currency": str(expected_currency).upper(),
            "status": "captured",
        }
    raise ValueError("tournament payment verification is not configured for this provider")


def fetch_tournament_payment(
    payment_id: str,
    expected_amount,
    expected_currency: str,
    order_id: str = None,
    expected_registration_id: str = None,
    expected_user_id: str = None,
) -> Dict[str, Any]:
    """Fetch an already-created provider payment for cron/webhook settlement."""
    if PROVIDER != "razorpay":
        raise ValueError("payment queue requires PAYMENT_PROVIDER=razorpay")
    return _rzp_fetch_tournament_payment(
        payment_id,
        expected_amount,
        expected_currency,
        order_id,
        expected_registration_id=expected_registration_id,
        expected_user_id=expected_user_id,
    )


def fetch_tournament_payment_for_order(
    order_id: str,
    expected_amount,
    expected_currency: str,
    expected_registration_id: str = None,
    expected_user_id: str = None,
) -> Dict[str, Any]:
    """Find and validate a captured/authorized Razorpay payment for an order."""
    if PROVIDER != "razorpay":
        raise ValueError("payment queue requires PAYMENT_PROVIDER=razorpay")
    return _rzp_fetch_tournament_payment_for_order(
        order_id,
        expected_amount,
        expected_currency,
        expected_registration_id=expected_registration_id,
        expected_user_id=expected_user_id,
    )


def refund_tournament_payment(
    payment_id: str,
    amount,
    currency: str,
    receipt: str,
    existing_refund_id: str = None,
    provider: str = None,
) -> Dict[str, Any]:
    """Create or recover one idempotent tournament registration refund."""
    selected_provider = str(provider or PROVIDER).lower()
    if selected_provider == "mock":
        return {
            "provider": "mock",
            "refund_id": existing_refund_id or f"rfnd_{receipt}",
            "payment_id": str(payment_id),
            "amount": Decimal(str(amount)).quantize(Decimal("0.01")),
            "currency": str(currency).upper(),
            "status": "processed",
            "receipt": receipt,
        }
    if selected_provider != "razorpay" or PROVIDER != "razorpay":
        raise ValueError("tournament refunds are not configured for this provider")
    return _rzp_refund_tournament_payment(
        payment_id,
        amount,
        currency,
        receipt,
        existing_refund_id=existing_refund_id,
    )


def fetch_tournament_refund(
    refund_id: str,
    payment_id: str,
    amount,
    currency: str,
    provider: str = None,
) -> Dict[str, Any]:
    """Fetch and validate a provider refund during reconciliation."""
    selected_provider = str(provider or PROVIDER).lower()
    if selected_provider == "mock":
        return {
            "provider": "mock",
            "refund_id": str(refund_id),
            "payment_id": str(payment_id),
            "amount": Decimal(str(amount)).quantize(Decimal("0.01")),
            "currency": str(currency).upper(),
            "status": "processed",
        }
    if selected_provider != "razorpay" or PROVIDER != "razorpay":
        raise ValueError("tournament refunds are not configured for this provider")
    return _rzp_fetch_tournament_refund(refund_id, payment_id, amount, currency)

# ---------------------------
# Mock provider (for dev/test)
# ---------------------------

def _mock_create_intent(amount: float, currency: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "provider": "mock",
        "amount": float(amount),
        "currency": currency,
        "client_secret": f"mock_cs_{int(time.time())}",
        "metadata": metadata,
        "status": "requires_payment_method"
    }

def _mock_verify_webhook(payload: bytes, signature: str) -> Tuple[bool, str, str]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception:
        return False, None, "failed"
    reg_id = str(data.get("registration_id") or data.get("data", {}).get("registration_id") or "")
    status = data.get("status") or data.get("data", {}).get("status") or "succeeded"
    return True, reg_id, status

# ---------------------------
# Razorpay (outline)
# ---------------------------

def _rzp_create_order(amount: float, currency: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creates a Razorpay order. Amount must be in the smallest unit (paise).
    """
    import requests
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise RuntimeError("Razorpay keys not configured")

    smallest = int(round(amount * 100))  # INR paise
    payload = {
        "amount": smallest,
        "currency": currency,
        "receipt": metadata.get("receipt") or metadata.get("registration_id") or f"rcpt_{int(time.time())}",
        "payment_capture": 1,
        "notes": metadata
    }
    resp = requests.post(
        "https://api.razorpay.com/v1/orders",
        auth=(key_id, key_secret),
        json=payload,
        timeout=10
    )
    _raise_for_razorpay_status(resp, "Razorpay order creation failed")
    order = resp.json()
    return {
        "provider": "razorpay",
        "order_id": order["id"],
        "amount": amount,
        "currency": currency,
        "key": key_id,
        "metadata": metadata,
        "status": "requires_payment_method"
    }

def _rzp_verify_webhook(payload: bytes, signature: str) -> Tuple[bool, str, str]:
    """
    Verify Razorpay webhook using webhook secret.
    """
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        return False, None, "failed"
    computed = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(computed, signature or ""):
        return False, None, "failed"

    try:
        event = _as_dict(json.loads(payload.decode("utf-8")))
    except Exception:
        return False, None, "failed"
    if not event:
        return False, None, "failed"

    # Map event types -> registration_id, status
    # Expect registration_id in notes/metadata
    payload_data = _as_dict(event.get("payload"))
    payment_entity = _razorpay_entity(payload_data, "payment")
    order_entity = _razorpay_entity(payload_data, "order")
    entity = payment_entity or order_entity
    notes = _razorpay_notes(entity)
    reg_id = (
        notes.get("registration_id")
        or _razorpay_notes(order_entity).get("registration_id")
        or order_entity.get("receipt")
        or entity.get("receipt")
    )

    # Infer status
    event_type = event.get("event")
    if event_type in {"payment.captured", "order.paid"}:
        status = "succeeded"
    elif event_type in {"payment.failed"}:
        status = "failed"
    else:
        status = "failed"

    return True, reg_id, status


def _rzp_verify_payment_success(data: Dict[str, Any]) -> Tuple[bool, str, str]:
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not key_secret:
        return False, None, "failed"

    order_id = data.get("razorpay_order_id") or data.get("order_id")
    payment_id = data.get("razorpay_payment_id") or data.get("payment_id")
    signature = data.get("razorpay_signature") or data.get("signature")
    registration_id = str(data.get("registration_id") or data.get("team_id") or "")
    if not order_id or not payment_id or not signature or not registration_id:
        return False, None, "failed"

    message = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(
        key=key_secret.encode("utf-8"),
        msg=message,
        digestmod=hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False, None, "failed"

    try:
        import requests
        key_id = os.getenv("RAZORPAY_KEY_ID")
        if key_id:
            resp = requests.get(
                f"https://api.razorpay.com/v1/orders/{order_id}",
                auth=(key_id, key_secret),
                timeout=10,
            )
            _raise_for_razorpay_status(resp, "Razorpay order lookup failed")
            order = resp.json()
            notes = _razorpay_notes(order)
            if str(order.get("receipt") or notes.get("registration_id") or "") != registration_id:
                return False, None, "failed"
    except Exception:
        return False, None, "failed"

    return True, registration_id, "succeeded"


def _razorpay_credentials():
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise ValueError("Razorpay keys not configured")
    return key_id, key_secret


def _amount_in_paise(amount) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _rzp_verify_tournament_payment(
    data: Dict[str, Any],
    expected_amount,
    expected_currency: str,
    expected_registration_id: str = None,
    expected_order_id: str = None,
    expected_user_id: str = None,
) -> Dict[str, Any]:
    order_id = str(data.get("razorpay_order_id") or data.get("order_id") or "").strip()
    payment_id = str(data.get("razorpay_payment_id") or data.get("payment_id") or "").strip()
    signature = str(data.get("razorpay_signature") or data.get("signature") or "").strip()
    logger.info(
        "razorpay_tournament_verify start registration_id=%s expected_order_id=%s expected_user_id=%s "
        "order_id=%s payment_id=%s signature_present=%s expected_amount=%s expected_currency=%s",
        expected_registration_id,
        _short(expected_order_id),
        expected_user_id,
        _short(order_id),
        _short(payment_id),
        bool(signature),
        expected_amount,
        expected_currency,
    )
    if not order_id or not payment_id or not signature:
        logger.warning(
            "razorpay_tournament_verify missing_fields registration_id=%s order_id_present=%s "
            "payment_id_present=%s signature_present=%s",
            expected_registration_id,
            bool(order_id),
            bool(payment_id),
            bool(signature),
        )
        raise ValueError("razorpay_order_id, razorpay_payment_id, and razorpay_signature are required")

    _, key_secret = _razorpay_credentials()
    expected_signature = hmac.new(
        key=key_secret.encode("utf-8"),
        msg=f"{order_id}|{payment_id}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        logger.warning(
            "razorpay_tournament_verify signature_failed registration_id=%s order_id=%s payment_id=%s",
            expected_registration_id,
            _short(order_id),
            _short(payment_id),
        )
        raise ValueError("Razorpay signature verification failed")
    if expected_order_id and order_id != str(expected_order_id):
        logger.warning(
            "razorpay_tournament_verify order_mismatch registration_id=%s expected_order_id=%s actual_order_id=%s",
            expected_registration_id,
            _short(expected_order_id),
            _short(order_id),
        )
        raise ValueError("Razorpay order does not match this payment attempt")
    logger.info(
        "razorpay_tournament_verify signature_ok registration_id=%s order_id=%s payment_id=%s",
        expected_registration_id,
        _short(order_id),
        _short(payment_id),
    )
    return _rzp_fetch_tournament_payment(
        payment_id,
        expected_amount,
        expected_currency,
        order_id,
        expected_registration_id=expected_registration_id,
        expected_user_id=expected_user_id,
    )


def _rzp_fetch_tournament_payment(
    payment_id: str,
    expected_amount,
    expected_currency: str,
    order_id: str = None,
    expected_registration_id: str = None,
    expected_user_id: str = None,
) -> Dict[str, Any]:
    import requests

    logger.info(
        "razorpay_tournament_fetch start registration_id=%s expected_user_id=%s expected_order_id=%s "
        "payment_id=%s expected_amount=%s expected_currency=%s",
        expected_registration_id,
        expected_user_id,
        _short(order_id),
        _short(payment_id),
        expected_amount,
        expected_currency,
    )
    key_id, key_secret = _razorpay_credentials()
    payment_response = requests.get(
        f"https://api.razorpay.com/v1/payments/{payment_id}",
        auth=(key_id, key_secret),
        timeout=10,
    )
    _raise_for_razorpay_status(payment_response, "Razorpay payment lookup failed")
    payment = payment_response.json()
    actual_order_id = str(payment.get("order_id") or "")
    logger.info(
        "razorpay_tournament_fetch payment_loaded registration_id=%s payment_id=%s actual_order_id=%s "
        "payment_status=%s payment_amount=%s payment_currency=%s",
        expected_registration_id,
        _short(payment.get("id") or payment_id),
        _short(actual_order_id),
        payment.get("status"),
        payment.get("amount"),
        payment.get("currency"),
    )
    if order_id and actual_order_id != str(order_id):
        logger.warning(
            "razorpay_tournament_fetch payment_order_mismatch registration_id=%s payment_id=%s expected_order_id=%s "
            "actual_order_id=%s",
            expected_registration_id,
            _short(payment_id),
            _short(order_id),
            _short(actual_order_id),
        )
        raise ValueError("payment does not belong to the supplied Razorpay order")
    if not actual_order_id:
        logger.warning(
            "razorpay_tournament_fetch payment_missing_order registration_id=%s payment_id=%s",
            expected_registration_id,
            _short(payment_id),
        )
        raise ValueError("Razorpay payment has no order")

    order_response = requests.get(
        f"https://api.razorpay.com/v1/orders/{actual_order_id}",
        auth=(key_id, key_secret),
        timeout=10,
    )
    _raise_for_razorpay_status(order_response, "Razorpay order lookup failed")
    order = order_response.json()
    logger.info(
        "razorpay_tournament_fetch order_loaded registration_id=%s order_id=%s receipt=%s order_amount=%s "
        "order_currency=%s order_notes_registration_id=%s order_notes_user_id=%s",
        expected_registration_id,
        _short(order.get("id") or actual_order_id),
        _short(order.get("receipt")),
        order.get("amount"),
        order.get("currency"),
        _razorpay_notes(order).get("registration_id"),
        _razorpay_notes(order).get("user_id"),
    )
    if expected_registration_id:
        expected_registration_id = str(expected_registration_id)
        notes = _razorpay_notes(order)
        receipt = str(order.get("receipt") or "")
        bound_to_registration = (
            str(notes.get("registration_id") or "") == expected_registration_id
            or receipt == expected_registration_id
            or receipt == f"ctr_{expected_registration_id.replace('-', '')}"
        )
        bound_to_user = _razorpay_order_bound_to_user(order, payment, expected_user_id)
        logger.info(
            "razorpay_tournament_fetch binding_check registration_id=%s order_id=%s receipt=%s "
            "bound_to_registration=%s bound_to_user=%s expected_user_id=%s",
            expected_registration_id,
            _short(actual_order_id),
            _short(receipt),
            bound_to_registration,
            bound_to_user,
            expected_user_id,
        )
        if not bound_to_registration and not bound_to_user:
            logger.warning(
                "razorpay_tournament_fetch binding_failed registration_id=%s order_id=%s payment_id=%s receipt=%s "
                "expected_user_id=%s order_notes_registration_id=%s order_notes_user_id=%s payment_notes_user_id=%s",
                expected_registration_id,
                _short(actual_order_id),
                _short(payment_id),
                _short(receipt),
                expected_user_id,
                notes.get("registration_id"),
                notes.get("user_id"),
                _razorpay_notes(payment).get("user_id"),
            )
            raise ValueError("Razorpay order is not bound to this registration")
    expected_paise = _amount_in_paise(expected_amount)
    expected_currency = str(expected_currency or "INR").upper()
    if payment.get("status") == "authorized" and os.getenv("RAZORPAY_AUTO_CAPTURE_AUTHORIZED", "true").lower() in {"1", "true", "yes"}:
        logger.info(
            "razorpay_tournament_fetch capture_authorized registration_id=%s payment_id=%s amount=%s currency=%s",
            expected_registration_id,
            _short(payment_id),
            expected_paise,
            expected_currency,
        )
        capture_response = requests.post(
            f"https://api.razorpay.com/v1/payments/{payment_id}/capture",
            auth=(key_id, key_secret),
            json={"amount": expected_paise, "currency": expected_currency},
            timeout=10,
        )
        _raise_for_razorpay_status(capture_response, "Razorpay payment capture failed")
        payment = capture_response.json()
        logger.info(
            "razorpay_tournament_fetch capture_result registration_id=%s payment_id=%s payment_status=%s",
            expected_registration_id,
            _short(payment_id),
            payment.get("status"),
        )
    if payment.get("status") != "captured":
        logger.warning(
            "razorpay_tournament_fetch not_captured registration_id=%s payment_id=%s payment_status=%s",
            expected_registration_id,
            _short(payment_id),
            payment.get("status") or "unknown",
        )
        raise ValueError(f"Razorpay payment is not captured (status: {payment.get('status') or 'unknown'})")
    if int(payment.get("amount") or 0) != expected_paise or int(order.get("amount") or 0) != expected_paise:
        logger.warning(
            "razorpay_tournament_fetch amount_mismatch registration_id=%s payment_id=%s expected_paise=%s "
            "payment_amount=%s order_amount=%s",
            expected_registration_id,
            _short(payment_id),
            expected_paise,
            payment.get("amount"),
            order.get("amount"),
        )
        raise ValueError("Razorpay payment amount does not match the tournament entry fee")
    if str(payment.get("currency") or "").upper() != expected_currency or str(order.get("currency") or "").upper() != expected_currency:
        logger.warning(
            "razorpay_tournament_fetch currency_mismatch registration_id=%s payment_id=%s expected_currency=%s "
            "payment_currency=%s order_currency=%s",
            expected_registration_id,
            _short(payment_id),
            expected_currency,
            payment.get("currency"),
            order.get("currency"),
        )
        raise ValueError("Razorpay payment currency does not match the tournament currency")
    logger.info(
        "razorpay_tournament_fetch verified registration_id=%s order_id=%s payment_id=%s amount=%s currency=%s",
        expected_registration_id,
        _short(actual_order_id),
        _short(payment_id),
        Decimal(expected_paise) / Decimal("100"),
        expected_currency,
    )
    return {
        "provider": "razorpay",
        "payment_id": str(payment.get("id") or payment_id),
        "order_id": actual_order_id,
        "amount": Decimal(expected_paise) / Decimal("100"),
        "currency": expected_currency,
        "status": "captured",
        "receipt": str(order.get("receipt") or "") or None,
        "notes": order.get("notes") or {},
    }


def _rzp_fetch_tournament_payment_for_order(
    order_id: str,
    expected_amount,
    expected_currency: str,
    expected_registration_id: str = None,
    expected_user_id: str = None,
) -> Dict[str, Any]:
    import requests

    order_id = str(order_id or "").strip()
    if not order_id:
        raise ValueError("Razorpay order ID is required")

    key_id, key_secret = _razorpay_credentials()
    response = requests.get(
        f"https://api.razorpay.com/v1/orders/{order_id}/payments",
        auth=(key_id, key_secret),
        timeout=10,
    )
    _raise_for_razorpay_status(response, "Razorpay order payments lookup failed")
    payload = response.json()
    payments = payload.get("items") or []
    preferred_statuses = {"captured": 0, "authorized": 1}
    candidates = sorted(
        (
            payment for payment in payments
            if str(payment.get("status") or "").lower() in preferred_statuses
        ),
        key=lambda payment: preferred_statuses[str(payment.get("status") or "").lower()],
    )
    if not candidates:
        raise ValueError("Razorpay order has no captured payment yet")
    return _rzp_fetch_tournament_payment(
        str(candidates[0].get("id") or ""),
        expected_amount,
        expected_currency,
        order_id,
        expected_registration_id=expected_registration_id,
        expected_user_id=expected_user_id,
    )


def _validated_refund(refund, payment_id: str, expected_amount, expected_currency: str) -> Dict[str, Any]:
    expected_paise = _amount_in_paise(expected_amount)
    expected_currency = str(expected_currency or "INR").upper()
    refund_id = str(refund.get("id") or "").strip()
    if not refund_id:
        raise ValueError("Razorpay refund has no ID")
    if str(refund.get("payment_id") or "") != str(payment_id):
        raise ValueError("Razorpay refund does not belong to the registration payment")
    if int(refund.get("amount") or 0) != expected_paise:
        raise ValueError("Razorpay refund amount does not match the registration payment")
    actual_currency = str(refund.get("currency") or "").upper()
    if actual_currency and actual_currency != expected_currency:
        raise ValueError("Razorpay refund currency does not match the registration payment")
    status = str(refund.get("status") or "").lower()
    if status not in {"pending", "processed", "failed"}:
        raise ValueError(f"Razorpay refund has an unsupported status: {status or 'unknown'}")
    return {
        "provider": "razorpay",
        "refund_id": refund_id,
        "payment_id": str(payment_id),
        "amount": Decimal(expected_paise) / Decimal("100"),
        "currency": expected_currency,
        "status": status,
        "receipt": refund.get("receipt"),
    }


def _rzp_fetch_tournament_refund(refund_id: str, payment_id: str, amount, currency: str) -> Dict[str, Any]:
    import requests

    key_id, key_secret = _razorpay_credentials()
    response = requests.get(
        f"https://api.razorpay.com/v1/refunds/{refund_id}",
        auth=(key_id, key_secret),
        timeout=10,
    )
    response.raise_for_status()
    return _validated_refund(response.json(), payment_id, amount, currency)


def _rzp_payment_refunds(payment_id: str):
    import requests

    key_id, key_secret = _razorpay_credentials()
    response = requests.get(
        f"https://api.razorpay.com/v1/payments/{payment_id}/refunds",
        auth=(key_id, key_secret),
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("items") or []


def _rzp_refund_tournament_payment(
    payment_id: str,
    amount,
    currency: str,
    receipt: str,
    existing_refund_id: str = None,
) -> Dict[str, Any]:
    import requests

    payment_id = str(payment_id or "").strip()
    receipt = str(receipt or "").strip()[:40]
    if not payment_id or not receipt:
        raise ValueError("payment_id and refund receipt are required")

    if existing_refund_id:
        existing = _rzp_fetch_tournament_refund(existing_refund_id, payment_id, amount, currency)
        if existing["status"] in {"pending", "processed"}:
            return existing

    matching = [
        refund for refund in _rzp_payment_refunds(payment_id)
        if str(refund.get("receipt") or "").startswith(receipt)
    ]
    for refund in matching:
        validated = _validated_refund(refund, payment_id, amount, currency)
        if validated["status"] in {"pending", "processed"}:
            return validated

    attempt = len(matching) + 1
    attempt_receipt = receipt if attempt == 1 else f"{receipt[:37]}_{attempt}"[:40]
    key_id, key_secret = _razorpay_credentials()
    payload = {
        "amount": _amount_in_paise(amount),
        "speed": "normal",
        "receipt": attempt_receipt,
        "notes": {"source": "community_tournament_registration"},
    }
    try:
        response = requests.post(
            f"https://api.razorpay.com/v1/payments/{payment_id}/refund",
            auth=(key_id, key_secret),
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        return _validated_refund(response.json(), payment_id, amount, currency)
    except Exception:
        # The request may have succeeded before a timeout. Recover it by receipt.
        for refund in _rzp_payment_refunds(payment_id):
            if str(refund.get("receipt") or "") == attempt_receipt:
                validated = _validated_refund(refund, payment_id, amount, currency)
                if validated["status"] in {"pending", "processed"}:
                    return validated
        raise

# ---------------------------
# Stripe (outline)
# ---------------------------

def _stripe_create_intent(amount: float, currency: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    import stripe
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise RuntimeError("Stripe key not configured")
    stripe.api_key = key
    intent = stripe.PaymentIntent.create(
        amount=int(round(amount * 100)),
        currency=currency,
        metadata=metadata,
        automatic_payment_methods={"enabled": True}
    )
    return {
        "provider": "stripe",
        "payment_intent": intent["id"],
        "client_secret": intent["client_secret"],
        "amount": amount,
        "currency": currency,
        "metadata": metadata,
        "status": intent["status"]
    }

def _stripe_verify_webhook(payload: bytes, signature: str) -> Tuple[bool, str, str]:
    import stripe
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not endpoint_secret:
        return False, None, "failed"
    try:
        event = stripe.Webhook.construct_event(
            payload=payload, sig_header=signature, secret=endpoint_secret
        )
    except Exception:
        return False, None, "failed"

    obj = event.get("data", {}).get("object", {})
    reg_id = None
    md = obj.get("metadata", {}) if isinstance(obj, dict) else {}
    reg_id = md.get("registration_id")

    etype = event.get("type")
    if etype in {"payment_intent.succeeded"}:
        status = "succeeded"
    elif etype in {"payment_intent.payment_failed"}:
        status = "failed"
    else:
        status = "failed"

    return True, reg_id, status
