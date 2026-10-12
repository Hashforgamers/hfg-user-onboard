import ast, os, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session,sessionmaker

@pytest.fixture
def coins():
    url=os.getenv('HASH_COIN_TEST_DATABASE_URL')
    if not url: pytest.skip('Requires disposable PostgreSQL')
    engine=create_engine(url);schema='coins_'+uuid.uuid4().hex
    with engine.begin() as c:
        c.execute(text(f'CREATE SCHEMA {schema}'))
    from sqlalchemy import event
    def checkout(c,*a):
        with c.cursor() as cursor:cursor.execute(f'SET search_path TO {schema}')
        c.commit()
    event.listen(engine,'checkout',checkout)
    with engine.begin() as c:
        c.execute(text('CREATE TABLE users(id integer PRIMARY KEY); INSERT INTO users VALUES(1),(2); CREATE TABLE user_hash_coins(id serial PRIMARY KEY,user_id integer UNIQUE REFERENCES users(id),hash_coins integer,updated_at timestamp); INSERT INTO user_hash_coins(user_id,hash_coins) VALUES(1,4000),(2,4000)'))
        c.execute(text((Path(__file__).parents[1]/'sql/20261011_hash_coin_spends.sql').read_text().replace('BEGIN;','').replace('COMMIT;','')))
        c.execute(text((Path(__file__).parents[1]/'sql/20261011_hash_coin_items.sql').read_text().replace('BEGIN;','').replace('COMMIT;','')))
        catalog=(Path(__file__).parents[1]/'sql/20261012_hash_coin_catalog.sql').read_text().replace('BEGIN;','').replace('COMMIT;','')
        c.execute(text(catalog));c.execute(text(catalog))
        c.execute(text("INSERT INTO hash_coin_items(source,item_id,price) VALUES ('ludo_skin_purchase','test_dice',500),('mini_game_cosmetic','test_theme',500)"))
    sessions=scoped_session(sessionmaker(bind=engine));scope={'db':SimpleNamespace(session=sessions)}
    tree=ast.parse((Path(__file__).parents[1]/'services/hash_coin_spend.py').read_text());tree.body=[n for n in tree.body if not isinstance(n,ast.ImportFrom) or n.module!='db.extensions'];exec(compile(tree,'spend','exec'),scope)
    yield scope['spend'],sessions
    sessions.remove();event.remove(engine,'checkout',checkout)
    with engine.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
    engine.dispose()

def buy(coins,ref='purchase',uid=1,**extra):
    spend,sessions=coins
    result,status=spend(uid,dict(amount=2000,source='arrow_escape_continue',reference_id=ref) | extra)
    sessions.commit() if status==200 else sessions.rollback()
    sessions.remove();return result,status

def test_receipt_replay_returns_original_balance_and_scopes_user(coins):
    assert buy(coins)==({'hash_coins':2000},200)
    assert buy(coins,'second')==({'hash_coins':0},200)
    assert buy(coins)==({'hash_coins':2000},200)
    assert buy(coins,uid=2)==({'hash_coins':2000},200)
    assert buy(coins,'third')==({'error':'insufficient_hash_coins','hash_coins':0},402)

def test_concurrent_same_reference_debits_once(coins):
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:buy(coins),range(4)))
    assert results==[({'hash_coins':2000},200)]*4

def test_competing_purchases_do_not_overdraw(coins):
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda n:buy(coins,str(n)),range(4)))
    assert sorted(status for _,status in results)==[200,200,402,402]

def test_price_and_input_validation(coins):
    spend,sessions=coins
    for body in [None,[],{'amount':True},{'amount':-2000},{'amount':2000,'source':'unknown','reference_id':'x'},{'amount':1,'source':'arrow_escape_continue','reference_id':'x'},{'amount':2000,'source':'arrow_escape_continue','reference_id':''}]:
        assert spend(1,body)[1]==400
    sessions.rollback()

def test_balance_and_receipt_rollback_together(coins):
    spend,sessions=coins
    assert spend(1,dict(amount=2000,source='arrow_escape_continue',reference_id='rollback'))[1]==200
    sessions.rollback();sessions.remove()
    assert buy(coins,'rollback')==({'hash_coins':2000},200)

@pytest.mark.parametrize('source,amount',[('arrow_escape_hint',200),('pac_man_continue',1000),('plant_vs_zombie_continue',1000),('wordly_reveal',300)])
def test_new_fixed_prices(coins,source,amount):
    assert buy(coins,source=source,amount=amount)==({'hash_coins':4000-amount},200)

def test_item_ownership_replay_price_change_and_repurchase(coins):
    args=dict(source='ludo_skin_purchase',amount=500,item_id='test_dice')
    assert buy(coins,**args)==({'hash_coins':3500},200)
    spend,sessions=coins
    sessions.execute(text("UPDATE hash_coin_items SET price=600,enabled=FALSE"));sessions.commit()
    assert buy(coins,**args)==({'hash_coins':3500},200)
    assert buy(coins,item_id='other',source='ludo_skin_purchase',amount=500)[0]['error']=='idempotency_conflict'
    sessions.execute(text("UPDATE hash_coin_items SET enabled=TRUE,price=500"));sessions.commit()
    assert buy(coins,'new',**args)[0]['error']=='item_already_owned'
    rows=sessions.execute(text('SELECT user_id,item_id FROM hash_coin_purchases')).all()
    assert rows==[(1,'test_dice')]
    history = spend.__globals__['purchases'](1)['purchases']
    assert len(history)==1 and history[0]['item_id']=='test_dice' and history[0]['amount']==500
    assert spend.__globals__['purchases'](2)=={'purchases':[]}
    assert buy(coins,uid=2,**args)==({'hash_coins':3500},200)

def test_item_validation_and_atomic_rollback(coins):
    assert buy(coins,source='mini_game_cosmetic',amount=500)[0]['error']=='invalid_item_id'
    assert buy(coins,source='mini_game_cosmetic',amount=500,item_id='unknown')[0]['error']=='unknown_item'
    assert buy(coins,source='mini_game_cosmetic',amount=400,item_id='test_theme')[0]['error']=='invalid_amount'
    spend,sessions=coins
    assert spend(1,dict(source='mini_game_cosmetic',amount=500,item_id='test_theme',reference_id='rollback'))[1]==200
    sessions.rollback()
    assert sessions.execute(text('SELECT count(*) FROM hash_coin_purchases')).scalar()==0
    assert buy(coins,'rollback',source='mini_game_cosmetic',amount=500,item_id='test_theme')==({'hash_coins':3500},200)

def test_concurrent_item_purchase_different_references(coins):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda n:buy(coins,str(n),source='ludo_skin_purchase',amount=500,item_id='test_dice'),range(4)))
    assert sorted(status for _,status in results)==[200,409,409,409]

def test_rush_upgrade_ladders_repeatable_and_unknown_rejected(coins):
    spend,sessions=coins
    for source,prices in spend.__globals__['UPGRADES'].items():
        for price in prices:
            sessions.execute(text('UPDATE user_hash_coins SET hash_coins=10000 WHERE user_id=1'));sessions.commit()
            assert buy(coins,source+str(price),source=source,amount=price)[1]==200
        assert buy(coins,source+'bad',source=source,amount=1)[0]['error']=='invalid_amount'
    assert buy(coins,'repeat',source='hash_rush_upgrade_fireRate',amount=60)[1]==200
    assert buy(coins,source='hash_rush_upgrade_unknown',amount=60)[0]['error']=='unknown_source'

def test_rush_skin_once_each_and_catalog_prices(coins):
    spend,sessions=coins
    for source,price in spend.__globals__['SKINS'].items():
        sessions.execute(text('UPDATE user_hash_coins SET hash_coins=10000 WHERE user_id=1'));sessions.commit()
        assert buy(coins,source,source=source,amount=price)[1]==200
        assert buy(coins,source,source=source,amount=price)[1]==200
        assert buy(coins,source+'again',source=source,amount=price)[0]['error']=='item_already_owned'
    for row in sessions.execute(text('SELECT source,item_id,price FROM hash_coin_items WHERE item_id NOT LIKE :test'),{'test':'test_%'}).all():
        sessions.execute(text('UPDATE user_hash_coins SET hash_coins=20000 WHERE user_id=1'));sessions.commit()
        assert buy(coins,row.item_id,source=row.source,item_id=row.item_id,amount=row.price)[1]==200
    assert len(spend.__globals__['purchases'](1)['purchases'])==63

def test_credit_endpoint_rejects_negative_boolean_and_nonobject():
    from flask import Flask,g,jsonify,request
    tree=ast.parse((Path(__file__).parents[1]/'controllers/user_controller.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='add_hash_coins');fn.decorator_list=[]
    scope=dict(g=g,jsonify=jsonify,request=request)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'credit','exec'),scope)
    app=Flask(__name__)
    for body in [{'amount':-2000},{'amount':True},['x'],{'amount':0}]:
        with app.test_request_context(json=body):
            g.auth_user_id=1
            assert scope['add_hash_coins']()[1]==400

def test_spend_route_rejects_expired_token_before_database():
    from flask import Flask,g,jsonify
    tree=ast.parse((Path(__file__).parents[1]/'controllers/user_controller.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='spend_hash_coins');fn.decorator_list=[]
    scope=dict(g=g,jsonify=jsonify)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'route','exec'),scope)
    app=Flask(__name__)
    with app.test_request_context():
        g.token_expired=True
        assert scope['spend_hash_coins']()[1]==401
