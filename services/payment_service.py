import os
import hmac
import hashlib
import json
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple, Dict, Any

PROVIDER = os.getenv("PAYMENT_PROVIDER", "mock").lower()    # "mock" | "razorpay" | "stripe"
CURRENCY_DEFAULT = os.getenv("PAYMENT_CURRENCY", "INR")

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
    event = json.loads(payload.decode("utf-8"))
    payload_data = event.get("payload", {})
    payment = payload_data.get("payment", {}).get("entity", {}) or {}
    order = payload_data.get("order", {}).get("entity", {}) or {}
    return {
        "registration_id": registration_id,
        "provider": "razorpay",
        "payment_id": str(payment.get("id") or "") or None,
        "order_id": str(payment.get("order_id") or order.get("id") or "") or None,
        "amount": Decimal(str(payment.get("amount") or 0)) / Decimal("100"),
        "currency": str(payment.get("currency") or order.get("currency") or "").upper(),
        "status": "captured" if status == "succeeded" else "failed",
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


def verify_tournament_payment(data: Dict[str, Any], expected_amount, expected_currency: str) -> Dict[str, Any]:
    """Return provider-verified payment details for one tournament registration.

    This validates the client callback and then verifies the provider-side payment
    record. It intentionally does not mutate database state; settlement remains
    the responsibility of the community tournament transaction.
    """
    if PROVIDER == "razorpay":
        return _rzp_verify_tournament_payment(data, expected_amount, expected_currency)
    if PROVIDER == "mock":
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


def fetch_tournament_payment(payment_id: str, expected_amount, expected_currency: str, order_id: str = None) -> Dict[str, Any]:
    """Fetch an already-created provider payment for cron/webhook settlement."""
    if PROVIDER != "razorpay":
        raise ValueError("payment queue requires PAYMENT_PROVIDER=razorpay")
    return _rzp_fetch_tournament_payment(payment_id, expected_amount, expected_currency, order_id)

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
        "receipt": metadata.get("registration_id") or f"rcpt_{int(time.time())}",
        "notes": metadata
    }
    resp = requests.post(
        "https://api.razorpay.com/v1/orders",
        auth=(key_id, key_secret),
        json=payload,
        timeout=10
    )
    resp.raise_for_status()
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
        event = json.loads(payload.decode("utf-8"))
    except Exception:
        return False, None, "failed"

    # Map event types -> registration_id, status
    # Expect registration_id in notes/metadata
    payload_data = event.get("payload", {})
    payment_entity = payload_data.get("payment", {}).get("entity", {}) or {}
    order_entity = payload_data.get("order", {}).get("entity", {}) or {}
    entity = payment_entity or order_entity
    notes = entity.get("notes", {}) if isinstance(entity, dict) else {}
    reg_id = (
        notes.get("registration_id")
        or order_entity.get("notes", {}).get("registration_id")
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
            resp.raise_for_status()
            order = resp.json()
            notes = order.get("notes") or {}
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


def _rzp_verify_tournament_payment(data: Dict[str, Any], expected_amount, expected_currency: str) -> Dict[str, Any]:
    order_id = str(data.get("razorpay_order_id") or data.get("order_id") or "").strip()
    payment_id = str(data.get("razorpay_payment_id") or data.get("payment_id") or "").strip()
    signature = str(data.get("razorpay_signature") or data.get("signature") or "").strip()
    if not order_id or not payment_id or not signature:
        raise ValueError("razorpay_order_id, razorpay_payment_id, and razorpay_signature are required")

    _, key_secret = _razorpay_credentials()
    expected_signature = hmac.new(
        key=key_secret.encode("utf-8"),
        msg=f"{order_id}|{payment_id}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        raise ValueError("Razorpay signature verification failed")
    return _rzp_fetch_tournament_payment(payment_id, expected_amount, expected_currency, order_id)


def _rzp_fetch_tournament_payment(payment_id: str, expected_amount, expected_currency: str, order_id: str = None) -> Dict[str, Any]:
    import requests

    key_id, key_secret = _razorpay_credentials()
    payment_response = requests.get(
        f"https://api.razorpay.com/v1/payments/{payment_id}",
        auth=(key_id, key_secret),
        timeout=10,
    )
    payment_response.raise_for_status()
    payment = payment_response.json()
    actual_order_id = str(payment.get("order_id") or "")
    if order_id and actual_order_id != str(order_id):
        raise ValueError("payment does not belong to the supplied Razorpay order")
    if not actual_order_id:
        raise ValueError("Razorpay payment has no order")

    order_response = requests.get(
        f"https://api.razorpay.com/v1/orders/{actual_order_id}",
        auth=(key_id, key_secret),
        timeout=10,
    )
    order_response.raise_for_status()
    order = order_response.json()
    expected_paise = _amount_in_paise(expected_amount)
    expected_currency = str(expected_currency or "INR").upper()
    if payment.get("status") == "authorized" and os.getenv("RAZORPAY_AUTO_CAPTURE_AUTHORIZED", "false").lower() in {"1", "true", "yes"}:
        capture_response = requests.post(
            f"https://api.razorpay.com/v1/payments/{payment_id}/capture",
            auth=(key_id, key_secret),
            json={"amount": expected_paise, "currency": expected_currency},
            timeout=10,
        )
        capture_response.raise_for_status()
        payment = capture_response.json()
    if payment.get("status") != "captured":
        raise ValueError(f"Razorpay payment is not captured (status: {payment.get('status') or 'unknown'})")
    if int(payment.get("amount") or 0) != expected_paise or int(order.get("amount") or 0) != expected_paise:
        raise ValueError("Razorpay payment amount does not match the tournament entry fee")
    if str(payment.get("currency") or "").upper() != expected_currency or str(order.get("currency") or "").upper() != expected_currency:
        raise ValueError("Razorpay payment currency does not match the tournament currency")
    return {
        "provider": "razorpay",
        "payment_id": str(payment.get("id") or payment_id),
        "order_id": actual_order_id,
        "amount": Decimal(expected_paise) / Decimal("100"),
        "currency": expected_currency,
        "status": "captured",
    }

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
