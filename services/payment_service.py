import os
import hmac
import hashlib
import json
import time
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
    entity = event.get("payload", {}).get("payment", {}).get("entity", {}) or event.get("payload", {}).get("order", {}).get("entity", {})
    notes = entity.get("notes", {}) if isinstance(entity, dict) else {}
    reg_id = notes.get("registration_id")

    # Infer status
    event_type = event.get("event")
    if event_type in {"payment.captured", "order.paid"}:
        status = "succeeded"
    elif event_type in {"payment.failed"}:
        status = "failed"
    else:
        status = "failed"

    return True, reg_id, status

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
