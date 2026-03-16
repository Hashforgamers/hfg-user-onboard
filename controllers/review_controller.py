from flask import Blueprint, request, jsonify, g
from sqlalchemy import text
from datetime import datetime, timedelta, timezone

from db.extensions import db
from models.cafeReview import CafeReview
from models.user import User
from services.security import auth_required_self

review_blueprint = Blueprint("reviews", __name__)

EDIT_WINDOW_HOURS = 24


def _clean_text(value, max_len=None):
    if value is None:
        return None
    text_val = str(value).strip()
    if not text_val:
        return None
    if max_len and len(text_val) > max_len:
        return text_val[:max_len]
    return text_val


def _rating_counts(vendor_id: int):
    row = db.session.execute(text("""
        SELECT
            COUNT(*)::int AS total,
            COALESCE(AVG(rating), 0) AS average,
            SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END)::int AS r5,
            SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END)::int AS r4,
            SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END)::int AS r3,
            SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END)::int AS r2,
            SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END)::int AS r1
        FROM cafe_reviews
        WHERE vendor_id = :vendor_id AND status = 'published'
    """), {"vendor_id": vendor_id}).mappings().first()
    if not row:
        return {"total": 0, "average": 0, "r1": 0, "r2": 0, "r3": 0, "r4": 0, "r5": 0}
    return {
        "total": int(row["total"] or 0),
        "average": float(row["average"] or 0),
        "r1": int(row["r1"] or 0),
        "r2": int(row["r2"] or 0),
        "r3": int(row["r3"] or 0),
        "r4": int(row["r4"] or 0),
        "r5": int(row["r5"] or 0),
    }


@review_blueprint.route("/reviews", methods=["POST"])
@auth_required_self(decrypt_user=True)
def create_review():
    user_id = g.auth_user_id
    data = request.get_json(silent=True) or {}

    vendor_id = data.get("vendor_id")
    booking_id = data.get("booking_id")
    rating = data.get("rating")
    title = _clean_text(data.get("title"), max_len=120)
    comment = _clean_text(data.get("comment"))
    is_anonymous = bool(data.get("is_anonymous", False))

    if not vendor_id or not booking_id or rating is None:
        return jsonify({"error": "vendor_id, booking_id, and rating are required"}), 400

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({"error": "rating must be an integer between 1 and 5"}), 400
    if rating < 1 or rating > 5:
        return jsonify({"error": "rating must be between 1 and 5"}), 400

    # Validate booking ownership + vendor match + completion
    booking_row = db.session.execute(text("""
        SELECT b.id AS booking_id, b.user_id, b.status, ag.vendor_id
        FROM bookings b
        JOIN available_games ag ON ag.id = b.game_id
        WHERE b.id = :booking_id
        LIMIT 1
    """), {"booking_id": booking_id}).mappings().first()

    if not booking_row:
        return jsonify({"error": "Booking not found"}), 404
    if int(booking_row["user_id"]) != int(user_id):
        return jsonify({"error": "Booking does not belong to user"}), 403
    if int(booking_row["vendor_id"]) != int(vendor_id):
        return jsonify({"error": "Vendor mismatch for booking"}), 400
    if str(booking_row["status"]).lower() != "completed":
        return jsonify({"error": "Review allowed only after session completion"}), 400

    existing = CafeReview.query.filter_by(booking_id=int(booking_id)).first()
    if existing:
        return jsonify({"error": "Review already submitted for this booking"}), 409

    user = User.query.filter_by(id=int(user_id)).first()
    review = CafeReview(
        vendor_id=int(vendor_id),
        user_id=int(user_id),
        booking_id=int(booking_id),
        rating=rating,
        title=title,
        comment=comment,
        is_anonymous=is_anonymous,
        user_name_snapshot=user.name if user else None,
        user_avatar_snapshot=user.avatar_path if user else None,
        status="published",
    )
    db.session.add(review)
    db.session.commit()

    return jsonify({
        "ok": True,
        "review_id": str(review.id),
        "created_at": review.created_at.isoformat() if review.created_at else None
    }), 201


@review_blueprint.route("/reviews/<uuid:review_id>", methods=["PATCH"])
@auth_required_self(decrypt_user=True)
def edit_review(review_id):
    user_id = g.auth_user_id
    data = request.get_json(silent=True) or {}
    review = CafeReview.query.filter_by(id=review_id).first()
    if not review:
        return jsonify({"error": "Review not found"}), 404
    if int(review.user_id) != int(user_id):
        return jsonify({"error": "Forbidden"}), 403

    # Enforce edit window
    created_at = review.created_at
    if created_at:
        now = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if now - created_at > timedelta(hours=EDIT_WINDOW_HOURS):
            return jsonify({"error": "Edit window expired"}), 400

    if "rating" in data:
        try:
            rating = int(data.get("rating"))
        except (TypeError, ValueError):
            return jsonify({"error": "rating must be an integer between 1 and 5"}), 400
        if rating < 1 or rating > 5:
            return jsonify({"error": "rating must be between 1 and 5"}), 400
        review.rating = rating

    if "title" in data:
        review.title = _clean_text(data.get("title"), max_len=120)
    if "comment" in data:
        review.comment = _clean_text(data.get("comment"))
    if "is_anonymous" in data:
        review.is_anonymous = bool(data.get("is_anonymous"))

    db.session.commit()
    return jsonify({"ok": True}), 200


@review_blueprint.route("/vendors/<int:vendor_id>/reviews", methods=["GET"])
def list_reviews(vendor_id):
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = max(int(request.args.get("offset", 0)), 0)
    rating = request.args.get("rating")
    sort = (request.args.get("sort") or "recent").lower()

    query = (
        db.session.query(CafeReview, User)
        .outerjoin(User, User.id == CafeReview.user_id)
        .filter(CafeReview.vendor_id == int(vendor_id), CafeReview.status == "published")
    )

    if rating:
        try:
            rating_val = int(rating)
            query = query.filter(CafeReview.rating == rating_val)
        except ValueError:
            pass

    if sort == "top":
        query = query.order_by(CafeReview.rating.desc(), CafeReview.created_at.desc())
    else:
        query = query.order_by(CafeReview.created_at.desc())

    rows = query.offset(offset).limit(limit).all()

    payload = []
    for review, user in rows:
        is_anon = bool(review.is_anonymous)
        name = review.user_name_snapshot or (user.name if user else None)
        avatar = review.user_avatar_snapshot or (user.avatar_path if user else None)
        payload.append({
            "id": str(review.id),
            "vendor_id": review.vendor_id,
            "rating": review.rating,
            "title": review.title,
            "comment": review.comment,
            "status": review.status,
            "created_at": review.created_at.isoformat() if review.created_at else None,
            "response_text": review.response_text,
            "responded_at": review.responded_at.isoformat() if review.responded_at else None,
            "user": {
                "id": None if is_anon else review.user_id,
                "name": "Anonymous" if is_anon else name,
                "avatar": None if is_anon else avatar,
            },
        })

    return jsonify({
        "items": payload,
        "limit": limit,
        "offset": offset,
        "count": len(payload),
    }), 200


@review_blueprint.route("/vendors/<int:vendor_id>/reviews/summary", methods=["GET"])
def reviews_summary(vendor_id):
    summary = _rating_counts(int(vendor_id))
    return jsonify(summary), 200
