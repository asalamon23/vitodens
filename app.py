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
    i,g,d=discover_with(get)
    base=feature_path(i,g,d)
    fs=get(base).get('data',[])
    f=next((x for x in fs if x.get('feature')==feature),None)
    if not f or not f.get('commands',{}).get(cmd,{}).get('isExecutable'):
        raise ValueError('Feature not executable')
    r=requests.post(BASE+base+'/'+feature+'/commands/'+cmd,
                    headers={'Authorization':'Bearer '+access},json=params,timeout=25)
    r.raise_for_status()

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
    received_state=request.args.get('state')
    expected_state=session.pop('oauth_state',None)
    if not received_state or not expected_state or not secrets.compare_digest(received_state,expected_state):
        app.logger.warning('OAuth state verification failed: session_state_present=%s callback_state_present=%s host=%s (values redacted)',bool(expected_state),bool(received_state),request.host)
        return 'Invalid OAuth state. Start at http://localhost:5000 and click Connect again; do not use 127.0.0.1.',400
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
