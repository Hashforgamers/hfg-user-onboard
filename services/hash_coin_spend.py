"""Atomic, priced HashCoin purchases; caller commits balance and receipt together."""
from sqlalchemy import text
from db.extensions import db

PRICES = {'arrow_escape_continue': 2000}

def spend(user_id, body):
    if not isinstance(body, dict):
        return {'error': 'invalid_request'}, 400
    amount, source, reference = (body.get(k) for k in ('amount', 'source', 'reference_id'))
    if type(amount) is not int or amount <= 0 or amount > 2147483647:
        return {'error': 'invalid_amount'}, 400
    if not isinstance(source, str) or source not in PRICES:
        return {'error': 'unknown_source'}, 400
    if amount != PRICES[source]:
        return {'error': 'invalid_amount'}, 400
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 128 or reference != reference.strip():
        return {'error': 'invalid_reference_id'}, 400
    # Creation races and subsequent purchases serialize on the user's balance row.
    db.session.execute(text('''INSERT INTO user_hash_coins(user_id,hash_coins,updated_at)
        VALUES (:uid,0,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO NOTHING'''), {'uid': user_id})
    balance = db.session.execute(text('SELECT hash_coins FROM user_hash_coins WHERE user_id=:uid FOR UPDATE'), {'uid': user_id}).scalar_one()
    previous = db.session.execute(text('''SELECT amount,source,balance_after FROM hash_coin_spends
        WHERE user_id=:uid AND reference_id=:ref'''), {'uid':user_id,'ref':reference}).mappings().first()
    if previous:
        if previous['amount'] != amount or previous['source'] != source:
            return {'error':'idempotency_conflict'}, 409
        return {'hash_coins':previous['balance_after']}, 200
    if (balance or 0) < amount:
        return {'error':'insufficient_hash_coins','hash_coins':balance or 0}, 402
    remaining = db.session.execute(text('''UPDATE user_hash_coins SET hash_coins=hash_coins-:amount,
        updated_at=CURRENT_TIMESTAMP WHERE user_id=:uid AND hash_coins>=:amount RETURNING hash_coins'''),
        {'uid':user_id,'amount':amount}).scalar_one()
    db.session.execute(text('''INSERT INTO hash_coin_spends(user_id,reference_id,source,amount,balance_after)
        VALUES (:uid,:ref,:source,:amount,:balance)'''),
        {'uid':user_id,'ref':reference,'source':source,'amount':amount,'balance':remaining})
    return {'hash_coins':remaining}, 200
