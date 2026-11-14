"""Persistent, single-process schedule runner. Start one application worker only."""
import sqlite3, json, time, threading, os
from datetime import datetime
from zoneinfo import ZoneInfo

DB=os.environ.get('SCHEDULE_DB','vitodens-schedules.sqlite3')
TZ=ZoneInfo(os.environ.get('APP_TIMEZONE','Europe/Bucharest'))
LOCK=threading.Lock()

def connection():
    c=sqlite3.connect(DB,timeout=10)
    c.execute('CREATE TABLE IF NOT EXISTS plans (id INTEGER PRIMARY KEY, owner TEXT, kind TEXT, feature TEXT, command TEXT, param TEXT, daytemp REAL, nighttemp REAL, start TEXT, end TEXT, days TEXT, enabled INTEGER DEFAULT 1, last_slot TEXT DEFAULT "")')
    c.execute('CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, owner TEXT, feature TEXT, command TEXT, param TEXT, target REAL, restore REAL, due REAL, state TEXT DEFAULT "pending", error TEXT DEFAULT "")')
    c.commit();return c

def plans(owner):
    with connection() as c:
        c.row_factory=sqlite3.Row
        return [dict(x) for x in c.execute('SELECT * FROM plans WHERE owner=? ORDER BY id DESC',(owner,))]

def save_plan(owner,d):
    with connection() as c:
        c.execute('INSERT INTO plans(owner,kind,feature,command,param,daytemp,nighttemp,start,end,days) VALUES(?,?,?,?,?,?,?,?,?,?)',(owner,d['kind'],d['feature'],d['command'],d['param'],d['daytemp'],d['nighttemp'],d['start'],d['end'],json.dumps(d['days'])))

def delete_plan(owner,pid):
    with connection() as c:c.execute('DELETE FROM plans WHERE owner=? AND id=?',(owner,pid))

def jobs(owner):
    with connection() as c:
        c.row_factory=sqlite3.Row
        return [dict(x) for x in c.execute('SELECT * FROM jobs WHERE owner=? AND state IN ("pending","failed")',(owner,))]

def boost(owner,d):
    with connection() as c:
        c.execute('INSERT INTO jobs(owner,feature,command,param,target,restore,due) VALUES(?,?,?,?,?,?,?)',(owner,d['feature'],d['command'],d['param'],d['target'],d['restore'],time.time()+d['minutes']*60))

def run_due(execute):
    """execute(owner, feature, command, params); caller handles auth refresh."""
    now=datetime.now(TZ);today=now.weekday();minute=now.strftime('%H:%M');slot=now.strftime('%Y-%m-%d %H:%M')
    with LOCK:
        with connection() as c:
            c.row_factory=sqlite3.Row
            for p in list(c.execute('SELECT * FROM plans WHERE enabled=1')):
                if today not in json.loads(p['days']) or p['last_slot']==slot:continue
                if minute not in (p['start'],p['end']):continue
                value=p['daytemp'] if minute==p['start'] else p['nighttemp']
                try:
                    execute(p['owner'],p['feature'],p['command'],{p['param']:value})
                    c.execute('UPDATE plans SET last_slot=? WHERE id=?',(slot,p['id']))
                except Exception as e:
                    print('Schedule failed',p['id'],str(e)[:150],flush=True)
            for j in list(c.execute('SELECT * FROM jobs WHERE state IN ("pending","failed") AND due<=?',(time.time(),))):
                try:
                    execute(j['owner'],j['feature'],j['command'],{j['param']:j['restore']})
                    c.execute('UPDATE jobs SET state="restored",error="" WHERE id=?',(j['id'],))
                except Exception as e:
                    c.execute('UPDATE jobs SET state="failed",error=? WHERE id=?',(str(e)[:180],j['id']))
            c.commit()

def start(execute):
    def loop():
        while True:
            try:run_due(execute)
            except Exception as e:print('Scheduler:',str(e)[:150],flush=True)
            time.sleep(20)
    threading.Thread(target=loop,daemon=True,name='schedule-runner').start()
