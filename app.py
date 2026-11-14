import os, secrets, hashlib, base64, time
from datetime import datetime
from urllib.parse import urlencode
from flask import Flask, render_template, request, redirect, session, jsonify
import requests
import scheduler

app=Flask(__name__, template_folder=os.path.join(getattr(__import__('sys'), '_MEIPASS', os.path.dirname(__file__)), 'templates'))
app.secret_key=os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
CLIENT_ID=os.environ.get('VIESSMANN_CLIENT_ID','').strip()
BASE='https://api.viessmann.com'
AUTH='https://iam.viessmann.com/idp/v2'
REDIRECT=os.environ.get('REDIRECT_URI','http://localhost:5000/callback')
# Single-user local application: token held in process memory, never exposed to browser.
TOKENS={}
# Tokens are held in memory; scheduled writes require this process to remain running.
# OAuth refresh tokens are not persisted; re-login is required after restart.

def verifier(): return base64.urlsafe_b64encode(secrets.token_bytes(40)).decode().rstrip('=')
def challenge(v): return base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip('=')
def uid():
    if 'uid' not in session: session['uid']=secrets.token_urlsafe(20)
    return session['uid']
def token_for(owner):
    t=TOKENS.get(owner)
    if not t: raise ValueError('Not connected. Sign in first.')
    if t.get('expires_at',0)<time.time()+90:
        r=requests.post(AUTH+'/token',data={'grant_type':'refresh_token','client_id':CLIENT_ID,'refresh_token':t['refresh_token']},timeout=20)
        r.raise_for_status(); fresh=r.json(); fresh['refresh_token']=fresh.get('refresh_token',t['refresh_token']);fresh['expires_at']=time.time()+fresh.get('expires_in',3600); TOKENS[owner]=fresh;t=fresh
    return t['access_token']
def token():return token_for(uid())

def api(path,method='GET',body=None):
    if not path.startswith('/iot/'): raise ValueError('Unsupported API path')
    r=requests.request(method,BASE+path,headers={'Authorization':'Bearer '+token(),'Accept':'application/json'},json=body,timeout=25)
    if not r.ok: raise ValueError('Viessmann API error '+str(r.status_code)+': '+r.text[:250])
    return r.json() if r.content else {}

def discover():
    installs=api('/iot/v2/equipment/installations?includeGateways=true').get('data',[])
    for inst in installs:
        for gateway in inst.get('gateways',[]):
            installation=str(inst['id']);serial=str(gateway['serial'])
            devices=api(f'/iot/v2/equipment/installations/{installation}/gateways/{serial}/devices').get('data',[])
            if devices:
                d=devices[0];return installation,serial,str(d['id'])
    raise ValueError('No connected Viessmann device found for this account.')

def feature_path(i,g,d): return f'/iot/v2/features/installations/{i}/gateways/{g}/devices/{d}/features'
def get_features():
    i,g,d=discover()
    return api(feature_path(i,g,d)).get('data',[])

def execute_scheduled(owner,feature,cmd,params):
    # Validate current capabilities before each automated write.
    access=token_for(owner)
    def get(path):
        r=requests.get(BASE+path,headers={'Authorization':'Bearer '+access},timeout=25)
        r.raise_for_status();return r.json()
    installs=get('/iot/v2/equipment/installations?includeGateways=true').get('data',[])
    for inst in installs:
        for gate in inst.get('gateways',[]):
            i=str(inst['id']);g=str(gate['serial'])
            devices=get(f'/iot/v2/equipment/installations/{i}/gateways/{g}/devices').get('data',[])
            if not devices:continue
            d=str(devices[0]['id']);base=feature_path(i,g,d)
            fs=get(base).get('data',[])
            f=next((x for x in fs if x.get('feature')==feature),None)
            if not f or not f.get('commands',{}).get(cmd,{}).get('isExecutable'):raise ValueError('Feature not executable')
            r=requests.post(BASE+base+'/'+feature+'/commands/'+cmd,headers={'Authorization':'Bearer '+access},json=params,timeout=25)
            r.raise_for_status();return
    raise ValueError('Device not found')

@app.route('/api/plans',methods=['GET','POST','DELETE'])
def plan_route():
    if uid() not in TOKENS:return jsonify({'error':'Connect to Viessmann first'}),401
    if request.method=='GET':return jsonify({'plans':scheduler.plans(uid()),'jobs':scheduler.jobs(uid())})
    d=request.get_json(silent=True) or {}
    if request.method=='DELETE':scheduler.delete_plan(uid(),int(d.get('id',0)));return jsonify({'ok':True})
    try:
        kind=d['kind'];feature=d['feature'];cmd=d['command'];param=d['param']
        assert kind in ('dhw','heating')
        assert (kind=='dhw' and feature in ('heating.dhw.temperature.main','heating.dhw.temperature') and cmd=='setTargetTemperature' and param=='temperature') or (kind=='heating' and feature.startswith('heating.circuits.') and feature.endswith(('.operating.programs.normal','.operating.programs.reduced','.operating.programs.comfort')) and cmd=='setTemperature' and param=='targetTemperature')
        for key in ('start','end'):datetime.strptime(d[key],'%H:%M')
        assert d['start']!=d['end']
        assert isinstance(d['days'],list) and len(d['days'])>0 and all(isinstance(x,int) and 0<=x<=6 for x in d['days'])
        fs=get_features();f=next(x for x in fs if x.get('feature')==feature)
        meta=f['commands'][cmd];assert meta['isExecutable']
        spec=meta.get('params',{}).get(param,{}).get('constraints',{})
        for k in ('daytemp','nighttemp'):
            v=float(d[k]);assert 10<=v<=60 if kind=='dhw' else 3<=v<=37
            assert spec.get('min',v)<=v<=spec.get('max',v)
        scheduler.save_plan(uid(),d)
        return jsonify({'ok':True})
    except (KeyError,ValueError,AssertionError,StopIteration,TypeError) as e:return jsonify({'error':'Unsupported feature or invalid schedule '+str(e)}),400

@app.route('/api/boost',methods=['POST'])
def boost_route():
    if uid() not in TOKENS:return jsonify({'error':'Connect first'}),401
    d=request.get_json(silent=True) or {}
    try:
        assert d['feature'] in ('heating.dhw.temperature.main','heating.dhw.temperature')
        assert d['command']=='setTargetTemperature' and d['param']=='temperature'
        assert 5<=int(d['minutes'])<=180
        fs=get_features();f=next(x for x in fs if x.get('feature')==d['feature'])
        meta=f['commands']['setTargetTemperature'];assert meta['isExecutable']
        spec=meta.get('params',{}).get('temperature',{}).get('constraints',{})
        target=float(d['target']);assert 10<=target<=60 and spec.get('min',target)<=target<=spec.get('max',target)
        # Read actual target before boost; do not trust a UI-provided restore value.
        old=f.get('properties',{}).get('value',{}).get('value')
        if old is None:old=f.get('properties',{}).get('temperature',{}).get('value')
        assert isinstance(old,(int,float))
        # Do not stack boosts; this avoids restoring a stale temperature.
        assert not scheduler.jobs(uid())
        execute_scheduled(uid(),d['feature'],'setTargetTemperature',{'temperature':target})
        scheduler.boost(uid(),dict(d,restore=old))
        return jsonify({'ok':True,'restore':old})
    except (KeyError,ValueError,AssertionError,StopIteration,TypeError) as e:return jsonify({'error':'Boost unavailable or invalid: '+str(e)}),400

@app.route('/')
def index():return render_template('index.html',configured=bool(CLIENT_ID))
@app.route('/login')
def login():
    if not CLIENT_ID:return 'Set VIESSMANN_CLIENT_ID in your environment first.',400
    v=verifier();state=secrets.token_urlsafe(24);session['pkce']=v;session['oauth_state']=state
    params={'client_id':CLIENT_ID,'redirect_uri':REDIRECT,'response_type':'code','scope':'IoT User offline_access','code_challenge':challenge(v),'code_challenge_method':'S256','state':state}
    return redirect(AUTH+'/authorize?'+urlencode(params))
@app.route('/callback')
def callback():
    if not request.args.get('state') or request.args.get('state')!=session.pop('oauth_state',None):return 'Invalid OAuth state',400
    code=request.args.get('code');v=session.pop('pkce',None)
    if not code or not v:return 'Missing authorization code',400
    r=requests.post(AUTH+'/token',data={'grant_type':'authorization_code','client_id':CLIENT_ID,'redirect_uri':REDIRECT,'code':code,'code_verifier':v},timeout=20)
    if not r.ok:return 'Token exchange failed: '+str(r.status_code),400
    t=r.json();t['expires_at']=time.time()+t.get('expires_in',3600);TOKENS[uid()]=t
    return redirect('/')
@app.route('/logout',methods=['POST'])
def logout():TOKENS.pop(uid(),None);return jsonify({'ok':True})
@app.route('/api/status')
def status():
    if uid() not in TOKENS:return jsonify({'connected':False})
    try:
        fs=get_features()
        # No invented values: return the actual feature objects from Viessmann.
        return jsonify({'connected':True,'features':fs,'updated':int(time.time())})
    except Exception as e:return jsonify({'connected':False,'error':str(e)}),502
@app.route('/api/command',methods=['POST'])
def command():
    if uid() not in TOKENS:return jsonify({'error':'Not connected'}),401
    data=request.get_json(silent=True) or {};feature=data.get('feature');cmd=data.get('command');params=data.get('params',{})
    if not isinstance(feature,str) or not isinstance(cmd,str) or not isinstance(params,dict):return jsonify({'error':'Invalid command'}),400
    try:
        fs=get_features();f=next((x for x in fs if x.get('feature')==feature),None)
        if not f:return jsonify({'error':'Feature not available'}),404
        command_meta=f.get('commands',{}).get(cmd)
        if not command_meta or not command_meta.get('isExecutable'):return jsonify({'error':'Command not supported or executable'}),403
        allowed=command_meta.get('params',{})
        if any(k not in allowed for k in params):return jsonify({'error':'Unknown parameter'}),400
        for k,meta in allowed.items():
            if meta.get('required') and k not in params:return jsonify({'error':'Missing parameter '+k}),400
            if k in params and isinstance(params[k],(int,float)):
                constraints=meta.get('constraints',{})
                if ('min' in constraints and params[k]<constraints['min']) or ('max' in constraints and params[k]>constraints['max']):return jsonify({'error':'Parameter outside device limits'}),400
        i,g,d=discover()
        path=feature_path(i,g,d)+'/'+feature+'/commands/'+cmd
        result=api(path,'POST',params)
        return jsonify({'ok':True,'result':result})
    except Exception as e:return jsonify({'error':str(e)}),502
if __name__=='__main__':
    scheduler.start(execute_scheduled)
    app.run(host='127.0.0.1',port=5000,debug=False)
