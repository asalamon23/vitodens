"""Vitodens Smart local Flask server. Compatible with existing launcher.py and scheduler.py."""
import os
import sys
import time
import secrets
import hashlib
import base64
from datetime import datetime
from urllib.parse import urlencode

import requests
from flask import Flask, render_template, request, redirect, session, jsonify
import scheduler

TEMPLATE_ROOT = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'templates')
app = Flask(__name__, template_folder=TEMPLATE_ROOT)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
CLIENT_ID = os.environ.get('VIESSMANN_CLIENT_ID', '').strip()
BASE = 'https://api.viessmann-climatesolutions.com'
AUTH = 'https://iam.viessmann-climatesolutions.com/idp/v3'
REDIRECT = os.environ.get('REDIRECT_URI', 'http://localhost:5000/callback')
TOKENS = {}  # In memory only; login again after restart.


def verifier():
    return base64.urlsafe_b64encode(secrets.token_bytes(40)).decode().rstrip('=')


def challenge(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()).decode().rstrip('=')


def uid():
    if 'uid' not in session:
        session['uid'] = secrets.token_urlsafe(20)
    return session['uid']


def token_for(owner):
    t = TOKENS.get(owner)
    if not t:
        raise ValueError('Not connected. Sign in first.')
    if t.get('expires_at', 0) < time.time() + 90:
        r = requests.post(AUTH + '/token', data={
            'grant_type': 'refresh_token', 'client_id': CLIENT_ID,
            'refresh_token': t['refresh_token']}, timeout=20)
        if not r.ok:
            raise ValueError('Token refresh failed: HTTP ' + str(r.status_code))
        fresh = r.json()
        fresh['refresh_token'] = fresh.get('refresh_token', t['refresh_token'])
        fresh['expires_at'] = time.time() + fresh.get('expires_in', 3600)
        TOKENS[owner] = fresh
        t = fresh
    return t['access_token']


def api_for(owner, path, method='GET', body=None):
    if not path.startswith('/iot/'):
        raise ValueError('Unsupported API path')
    r = requests.request(method, BASE + path, headers={
        'Authorization': 'Bearer ' + token_for(owner),
        'Accept': 'application/json'}, json=body, timeout=25)
    if not r.ok:
        raise ValueError('Viessmann API error ' + str(r.status_code) + ': ' + r.text[:350])
    return r.json() if r.content else {}


def api(path, method='GET', body=None):
    return api_for(uid(), path, method, body)


def records(payload):
    data = payload.get('data', []) if isinstance(payload, dict) else payload
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('installations', 'gateways', 'devices', 'features'):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return []


def discover_for(owner):
    installations = records(api_for(owner, '/iot/v2/equipment/installations'))
    for inst in installations:
        if not isinstance(inst, dict) or inst.get('id') is None:
            continue
        installation = str(inst['id'])
        gateways = inst.get('gateways')
        if not isinstance(gateways, list) or not gateways:
            gateways = records(api_for(owner, f'/iot/v2/equipment/installations/{installation}/gateways'))
        for gateway in gateways:
            if not isinstance(gateway, dict):
                continue
            serial = gateway.get('serial') or gateway.get('gatewaySerial')
            if not serial:
                continue
            serial = str(serial)
            devices = records(api_for(owner, f'/iot/v2/equipment/installations/{installation}/gateways/{serial}/devices'))
            for device in devices:
                if isinstance(device, dict) and device.get('id') is not None:
                    return installation, serial, str(device['id'])
    raise ValueError('No connected Viessmann device found. Check installation/gateway access.')


def discover():
    return discover_for(uid())


def feature_path(i, g, d):
    return f'/iot/v2/features/installations/{i}/gateways/{g}/devices/{d}/features'


def features_for(owner):
    i, g, d = discover_for(owner)
    return records(api_for(owner, feature_path(i, g, d)))


def get_features():
    return features_for(uid())


def feature_named(fs, name):
    return next((f for f in fs if isinstance(f, dict) and f.get('feature') == name), None)


def executable_meta(feature, cmd):
    meta = (feature.get('commands') or {}).get(cmd)
    if not isinstance(meta, dict) or not meta.get('isExecutable'):
        raise ValueError('Command not supported or executable by this device')
    return meta


def validate_params(meta, params):
    allowed = meta.get('params') or {}
    if any(k not in allowed for k in params):
        raise ValueError('Unknown command parameter')
    for k, spec in allowed.items():
        if spec.get('required') and k not in params:
            raise ValueError('Missing parameter ' + k)
        if k in params and isinstance(params[k], (int, float)) and not isinstance(params[k], bool):
            constraints = spec.get('constraints') or {}
            if ('min' in constraints and params[k] < constraints['min']) or ('max' in constraints and params[k] > constraints['max']):
                raise ValueError('Temperature outside device limits')


def execute_scheduled(owner, feature, cmd, params):
    fs = features_for(owner)
    f = feature_named(fs, feature)
    if not f:
        raise ValueError('Scheduled feature not available')
    validate_params(executable_meta(f, cmd), params)
    i, g, d = discover_for(owner)
    return api_for(owner, feature_path(i, g, d) + '/' + feature + '/commands/' + cmd, 'POST', params)


@app.route('/')
def index():
    return render_template('index.html', configured=bool(CLIENT_ID))


@app.route('/login')
def login():
    if not CLIENT_ID:
        return 'Set VIESSMANN_CLIENT_ID before connecting.', 400
    v = verifier()
    state = secrets.token_urlsafe(24)
    session['pkce'] = v
    session['oauth_state'] = state
    params = {'client_id': CLIENT_ID, 'redirect_uri': REDIRECT,
              'response_type': 'code', 'scope': 'IoT User offline_access',
              'code_challenge': challenge(v), 'code_challenge_method': 'S256',
              'state': state}
    return redirect(AUTH + '/authorize?' + urlencode(params))


@app.route('/callback')
def callback():
    received = request.args.get('state')
    expected = session.pop('oauth_state', None)
    if not received or not expected or not secrets.compare_digest(received, expected):
        app.logger.warning('OAuth state validation failed (missing cookie or different hostname/session)')
        return 'Invalid OAuth state. Start from http://localhost:5000 and click Connect again.', 400
    code = request.args.get('code')
    v = session.pop('pkce', None)
    if not code or not v:
        return 'Missing authorization code or PKCE verifier', 400
    r = requests.post(AUTH + '/token', data={
        'grant_type': 'authorization_code', 'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT, 'code': code, 'code_verifier': v}, timeout=20)
    if not r.ok:
        return 'Token exchange failed: HTTP ' + str(r.status_code), 400
    t = r.json()
    t['expires_at'] = time.time() + t.get('expires_in', 3600)
    TOKENS[uid()] = t
    return redirect('/')


@app.route('/logout', methods=['POST'])
def logout():
    TOKENS.pop(uid(), None)
    return jsonify({'ok': True})


@app.route('/api/status')
def status():
    if uid() not in TOKENS:
        return jsonify({'connected': False})
    try:
        return jsonify({'connected': True, 'features': get_features(), 'updated': int(time.time())})
    except Exception as e:
        return jsonify({'connected': False, 'error': str(e)}), 502


@app.route('/api/command', methods=['POST'])
def command():
    if uid() not in TOKENS:
        return jsonify({'error': 'Not connected'}), 401
    data = request.get_json(silent=True) or {}
    feature, cmd, params = data.get('feature'), data.get('command'), data.get('params', {})
    if not isinstance(feature, str) or not isinstance(cmd, str) or not isinstance(params, dict):
        return jsonify({'error': 'Invalid command'}), 400
    try:
        fs = get_features()
        f = feature_named(fs, feature)
        if not f:
            return jsonify({'error': 'Feature not available'}), 404
        validate_params(executable_meta(f, cmd), params)
        i, g, d = discover()
        result = api(feature_path(i, g, d) + '/' + feature + '/commands/' + cmd, 'POST', params)
        return jsonify({'ok': True, 'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/api/plans', methods=['GET', 'POST', 'DELETE'])
def plan_route():
    owner = uid()
    if owner not in TOKENS:
        return jsonify({'error': 'Connect to Viessmann first'}), 401
    if request.method == 'GET':
        return jsonify({'plans': scheduler.plans(owner), 'jobs': scheduler.jobs(owner)})
    data = request.get_json(silent=True) or {}
    if request.method == 'DELETE':
        try:
            scheduler.delete_plan(owner, int(data.get('id', 0)))
            return jsonify({'ok': True})
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid plan ID'}), 400
    try:
        kind, feature, cmd, param = (data[k] for k in ('kind', 'feature', 'command', 'param'))
        dhw = (kind == 'dhw' and feature in ('heating.dhw.temperature.main', 'heating.dhw.temperature')
               and cmd == 'setTargetTemperature' and param == 'temperature')
        heating = (kind == 'heating' and feature.startswith('heating.circuits.')
                   and feature.endswith(('.operating.programs.normal', '.operating.programs.reduced', '.operating.programs.comfort'))
                   and cmd == 'setTemperature' and param == 'targetTemperature')
        if not (dhw or heating):
            raise ValueError('Unsupported scheduling command')
        for k in ('start', 'end'):
            datetime.strptime(data[k], '%H:%M')
        if data['start'] == data['end']:
            raise ValueError('Start and end must differ')
        days = data['days']
        if not isinstance(days, list) or not days or any(type(x) is not int or x < 0 or x > 6 for x in days):
            raise ValueError('Invalid weekdays')
        f = feature_named(get_features(), feature)
        if not f:
            raise ValueError('Feature not available')
        meta = executable_meta(f, cmd)
        for k in ('daytemp', 'nighttemp'):
            val = float(data[k])
            if not ((10 <= val <= 60) if dhw else (3 <= val <= 37)):
                raise ValueError('Temperature outside app safety range')
            validate_params(meta, {param: val})
        scheduler.save_plan(owner, data)
        return jsonify({'ok': True})
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({'error': 'Invalid schedule: ' + str(e)}), 400


@app.route('/api/boost', methods=['POST'])
def boost_route():
    owner = uid()
    if owner not in TOKENS:
        return jsonify({'error': 'Connect first'}), 401
    data = request.get_json(silent=True) or {}
    try:
        feature = data['feature']
        if feature not in ('heating.dhw.temperature.main', 'heating.dhw.temperature'):
            raise ValueError('Unsupported hot-water feature')
        if data['command'] != 'setTargetTemperature' or data['param'] != 'temperature':
            raise ValueError('Unsupported boost command')
        minutes, target = int(data['minutes']), float(data['target'])
        if not 5 <= minutes <= 180 or not 10 <= target <= 60:
            raise ValueError('Boost duration or target outside app limits')
        f = feature_named(get_features(), feature)
        if not f:
            raise ValueError('Hot-water feature not available')
        validate_params(executable_meta(f, 'setTargetTemperature'), {'temperature': target})
        props = f.get('properties') or {}
        old = (props.get('value') or {}).get('value')
        if old is None:
            old = (props.get('temperature') or {}).get('value')
        if type(old) not in (int, float):
            raise ValueError('Cannot read previous temperature for safe restore')
        if scheduler.jobs(owner):
            raise ValueError('Another boost/restore job is already active')
        # WARNING: Restoration depends on this process staying running and OAuth remaining valid.
        execute_scheduled(owner, feature, 'setTargetTemperature', {'temperature': target})
        scheduler.boost(owner, dict(data, restore=old))
        return jsonify({'ok': True, 'restore': old})
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({'error': 'Boost unavailable: ' + str(e)}), 400


if __name__ == '__main__':
    scheduler.start(execute_scheduled)
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
