from sqlalchemy import text
from db.extensions import db

DEFAULT_SETTINGS = dict(context='',enabled=True,fallback_title='Plan your next gaming session',
                        fallback_message='Explore nearby gaming cafes and book a time that suits you.')


def load_notification_context():
    row=db.session.execute(text('SELECT context,enabled,fallback_title,fallback_message,updated_at::text FROM notification_campaign_settings WHERE id=1')).mappings().first()
    return dict(row) if row else dict(DEFAULT_SETTINGS)


def validate_notification_context(data):
    if not isinstance(data,dict): raise ValueError('Send a JSON object.')
    fields={name:str(data.get(name) or '').strip() for name in ('context','fallback_title','fallback_message')}
    for name,limit in [('context',6000),('fallback_title',80),('fallback_message',200)]:
        if not fields[name] or len(fields[name])>limit:
            raise ValueError(f'{name.replace("_"," ").capitalize()} is required and must be at most {limit} characters.')
    if type(data.get('enabled')) is not bool: raise ValueError('Enabled must be true or false.')
    return dict(fields,enabled=data['enabled'])
