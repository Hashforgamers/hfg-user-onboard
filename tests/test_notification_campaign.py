import ast
import logging
from pathlib import Path
from types import SimpleNamespace

SOURCE=Path(__file__).resolve().parents[1]/'job/daily_notifier.py'
node=next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='generate_notification')


def generator(client):
    scope=dict(logging=logging,gemini_agent=lambda:client,HASH_AGENT_PROMPT='old booking prompt')
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),scope)
    return scope['generate_notification']

SETTINGS=dict(context='Promote the Sunday tournament; no booking CTA.',enabled=True,fallback_title='Tournament update',fallback_message='Check the tournament page for details.')


def test_saved_context_replaces_old_campaign():
    calls=[]
    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text='Title: Join the tournament\nMessage: Explore Sunday tournament details in the app.')
    result=generator(SimpleNamespace(models=SimpleNamespace(generate_content=generate)))(SETTINGS)
    assert SETTINGS['context'] in calls[0]['contents']
    assert 'old booking prompt' not in calls[0]['contents']
    assert result['source']=='ai'


def test_ai_failure_uses_configured_fallback():
    result=generator(None)(SETTINGS)
    assert result==dict(title=SETTINGS['fallback_title'],message=SETTINGS['fallback_message'],source='fallback')


def test_invalid_ai_response_uses_configured_fallback():
    client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw:SimpleNamespace(text='not a notification')))
    assert generator(client)(SETTINGS)['source']=='fallback'


def test_paused_cron_queues_nothing_and_preview_sends_no_push(monkeypatch):
    import sys,types
    from flask import Flask,request,jsonify,current_app
    controller=SOURCE.parents[1]/'controllers/user_controller.py'
    names={'cron_trigger_daily_notifications','preview_campaign_notification'}
    nodes=[n for n in ast.parse(controller.read_text()).body if isinstance(n,ast.FunctionDef) and n.name in names]
    for item in nodes:item.decorator_list=[]
    module=types.ModuleType('services.notification_context')
    module.load_notification_context=lambda:dict(SETTINGS,enabled=False)
    module.validate_notification_context=lambda data: data
    monkeypatch.setitem(sys.modules,'services.notification_context',module)
    monkeypatch.setenv('SUPER_ADMIN_API_KEY','test-admin-secret')
    calls=[]
    def unexpected(*args,**kw):raise AssertionError('Pause or preview must not queue or send FCM')
    scope=dict(request=request,jsonify=jsonify,current_app=current_app,
        _is_valid_cron_request=lambda:True,
        _NOTIFICATION_JOB_EXECUTOR=SimpleNamespace(submit=unexpected),
        generate_notification=lambda settings:(calls.append(settings) or {'title':'Preview','message':'Sample','source':'ai'}))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(controller),'exec'),scope)
    app=Flask(__name__)
    app.add_url_rule('/cron',view_func=scope['cron_trigger_daily_notifications'],methods=['POST'])
    app.add_url_rule('/preview',view_func=scope['preview_campaign_notification'],methods=['POST'])
    client=app.test_client()
    paused=client.post('/cron',json={'force':True})
    assert paused.status_code==200 and paused.json['skipped'] is True
    assert not calls
    assert client.post('/preview',json=SETTINGS).status_code==401
    assert not calls
    preview=client.post('/preview',json=SETTINGS,headers={'X-Admin-Key':'test-admin-secret'})
    assert preview.status_code==200 and preview.json['data']['source']=='ai'
    assert len(calls)==1
