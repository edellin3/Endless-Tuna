"""Persist model IDs only, in the real collection DB. No credentials are stored."""
import json
from dataclasses import replace
from . import db
from .las import LASConfig, LASClient, LASError


def read_setting(key, default=''):
    with db.connect('real') as con:
        row = con.execute('SELECT value FROM app_settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default


def write_setting(key, value):
    with db.connect('real') as con:
        con.execute('INSERT INTO app_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))


def configured_client():
    config = LASConfig.from_env()
    selected = read_setting('las_selected_model')
    if selected and read_setting('las_selected_base') == config.normalized_url():
        config = replace(config, model=selected)
    return LASClient(config)


def status():
    try:
        client = configured_client()
        c = client.config
        c.require()
        return {'configured': True, 'credentials_configured': bool(c.api_key),
                'model': c.model, 'model_configured': bool(c.model),
                'status': 'configured_unverified', 'inference_enabled': bool(c.model),
                'message': 'Configuration present. Use Check connection and Test model to verify access.'}
    except LASError as error:
        import os
        key = os.environ.get('LAS_API_KEY', os.environ.get('OPENAI_KEY', '')).strip()
        return {'configured': False, 'credentials_configured': bool(key), 'model': '',
                'model_configured': False, 'inference_enabled': False, 'status': error.code,
                'message': str(error)}


def discover():
    client = configured_client()
    ids = client.discover_models()
    write_setting('las_discovered_models', json.dumps(ids))
    write_setting('las_discovery_base', client.config.normalized_url())
    return {'ok': True, 'code': 'connected', 'models': ids,
            'message': 'Live model discovery succeeded. Completion access has not been tested.'}


def select(model):
    client = configured_client()
    if (read_setting('las_discovery_base') != client.config.normalized_url()
            or model not in json.loads(read_setting('las_discovered_models', '[]'))):
        raise LASError('invalid_model', 'Check connection, then choose an ID returned by model discovery.')
    with db.connect('real') as con:
        for key, value in [('las_selected_model', model), ('las_selected_base', client.config.normalized_url())]:
            con.execute('INSERT INTO app_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
    return {'ok': True, 'code': 'model_selected', 'model': model,
            'message': 'Model selection saved on the server. No completion was sent.'}


def test_model():
    # Explicit POST action only. Do not return generated content to diagnostics.
    configured_client().complete([{'role': 'user', 'content': 'Reply with OK.'}], max_tokens=8)
    return {'ok': True, 'code': 'model_verified', 'message': 'A live tiny chat completion succeeded.'}
