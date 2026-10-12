"""Atomic, priced HashCoin purchases; caller commits balance and ownership together."""
from sqlalchemy import text
from db.extensions import db

PRICES = {'arrow_escape_continue': 2000, 'arrow_escape_hint': 200,
          'pac_man_continue': 1000, 'plant_vs_zombie_continue': 1000,
          'wordly_reveal': 300, 'hash_rush_continue': 1000}
UPGRADE_PRICES = {
    'fireRate': [60,80,105,140,180,240,315,420,555,730,965,1270,1680,2215,2925],
    'cannonPower': [60,80,105,140,180,240,315,420,555,730,965,1270,1680,2215,2925],
    'startArmy': [50,65,85,110,145,185,240,315,410,530,690,895,1165,1515,1970],
    'unitDamage': [70,95,125,170,225,300,405,545,730,975,1305,1750,2345,3145,4215],
    'unitHealth': [70,95,125,170,225,300,405,545,730,975,1305,1750,2345,3145,4215],
    'abilityCooldown': [90,125,175,245,345,485,680,950,1330,1860],
}
UPGRADES = {'hash_rush_upgrade_'+key: prices for key,prices in UPGRADE_PRICES.items()}
SKINS = {'hash_rush_skin_'+kind+'_'+item: price
         for kind in ('army','cannon')
         for item,price in {'emerald':150,'royal':300,'arctic':500,'shadow':800,'gold':1200}.items()}
ITEM_SOURCES = {'ludo_skin_purchase', 'mini_game_cosmetic'}

def purchases(user_id):
    rows = db.session.execute(text('''SELECT p.source,p.item_id,s.amount,p.purchased_at
        FROM hash_coin_purchases p JOIN hash_coin_spends s ON s.id=p.spend_id
        WHERE p.user_id=:uid ORDER BY p.purchased_at,p.source,p.item_id'''), {'uid':user_id}).mappings().all()
    return {'purchases':[dict(source=r['source'],item_id=r['item_id'],amount=r['amount'],
        purchased_at=r['purchased_at'].isoformat()+'Z') for r in rows]}

def spend(user_id, body):
    if not isinstance(body, dict): return {'error':'invalid_request'},400
    amount, source, reference = (body.get(k) for k in ('amount','source','reference_id'))
    item = body.get('item_id')
    if type(amount) is not int or amount <= 0 or amount > 2147483647:
        return {'error':'invalid_amount'},400
    if not isinstance(source,str) or source not in PRICES.keys() | ITEM_SOURCES | UPGRADES.keys() | SKINS.keys():
        return {'error':'unknown_source'},400
    if source in SKINS:
        if item is not None: return {'error':'invalid_item_id'},400
        item = source.rsplit('_',1)[-1]
    elif source in ITEM_SOURCES:
        if not isinstance(item,str) or not item or len(item)>128 or item!=item.strip():
            return {'error':'invalid_item_id'},400
    elif item is not None:
        return {'error':'invalid_item_id'},400
    if not isinstance(reference,str) or not reference.strip() or len(reference)>128 or reference!=reference.strip():
        return {'error':'invalid_reference_id'},400
    db.session.execute(text('''INSERT INTO user_hash_coins(user_id,hash_coins,updated_at)
        VALUES (:uid,0,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO NOTHING'''), {'uid':user_id})
    balance = db.session.execute(text('SELECT hash_coins FROM user_hash_coins WHERE user_id=:uid FOR UPDATE'), {'uid':user_id}).scalar_one()
    previous = db.session.execute(text('''SELECT amount,source,item_id,balance_after FROM hash_coin_spends
        WHERE user_id=:uid AND reference_id=:ref'''), {'uid':user_id,'ref':reference}).mappings().first()
    if previous:
        if previous['amount']!=amount or previous['source']!=source or previous['item_id']!=item:
            return {'error':'idempotency_conflict'},409
        return {'hash_coins':previous['balance_after']},200
    if source in ITEM_SOURCES:
        price = db.session.execute(text('''SELECT price FROM hash_coin_items
            WHERE source=:source AND item_id=:item AND enabled=TRUE FOR SHARE'''), {'source':source,'item':item}).scalar()
        if price is None: return {'error':'unknown_item'},400
    elif source in SKINS: price = SKINS[source]
    elif source in UPGRADES:
        if amount not in UPGRADES[source]: return {'error':'invalid_amount'},400
        price = amount
    else: price = PRICES[source]
    if item is not None:
        owned = db.session.execute(text('''SELECT 1 FROM hash_coin_purchases
            WHERE user_id=:uid AND source=:source AND item_id=:item'''), {'uid':user_id,'source':source,'item':item}).scalar()
        if owned: return {'error':'item_already_owned','hash_coins':balance or 0},409
    if amount!=price: return {'error':'invalid_amount'},400
    if (balance or 0)<amount: return {'error':'insufficient_hash_coins','hash_coins':balance or 0},402
    remaining = db.session.execute(text('''UPDATE user_hash_coins SET hash_coins=hash_coins-:amount,
        updated_at=CURRENT_TIMESTAMP WHERE user_id=:uid AND hash_coins>=:amount RETURNING hash_coins'''), {'uid':user_id,'amount':amount}).scalar_one()
    receipt = db.session.execute(text('''INSERT INTO hash_coin_spends(user_id,reference_id,source,item_id,amount,balance_after)
        VALUES (:uid,:ref,:source,:item,:amount,:balance) RETURNING id'''), {'uid':user_id,'ref':reference,'source':source,'item':item,'amount':amount,'balance':remaining}).scalar_one()
    if item is not None:
        db.session.execute(text('''INSERT INTO hash_coin_purchases(user_id,source,item_id,spend_id)
            VALUES (:uid,:source,:item,:receipt)'''), {'uid':user_id,'source':source,'item':item,'receipt':receipt})
    return {'hash_coins':remaining},200
