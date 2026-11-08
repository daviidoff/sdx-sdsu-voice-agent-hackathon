import time
from fastapi.testclient import TestClient
from app.backend import create_app
from app.contacts import Search

POLYGON = [[32.79,-117.18],[32.79,-117.09],[32.70,-117.09],[32.70,-117.18]]


def search(client, identifier='search1'):
    response = client.post('/api/contacts/searches', json={'id': identifier, 'provider': 'mock', 'polygon': POLYGON})
    assert response.status_code == 202, response.text
    for _ in range(100):
        snapshot = client.get('/api/dashboard/snapshot').json()
        job = next(j for j in snapshot['contact_workflow']['searches'] if j['id'] == identifier)
        if job['status'] not in ('queued', 'running'): break
        time.sleep(.01)
    assert job['status'] in ('completed', 'partial'), job
    assert job['workers'] and all(w['status'] != 'running' for w in job['workers'].values())
    return [f for f in snapshot['facilities'] if f['id'] in job['facility_ids']]


def test_search_polygon_and_replay(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    with TestClient(create_app(tmp_path/'db')) as client:
        found = search(client)
        assert found and all(32.70 <= f['latitude'] <= 32.79 for f in found)
        assert all(f['incident_id'] == 'san-diego-demo' and f['simulated'] for f in found)
        assert not any('Distant' in f['name'] or 'South' in f['name'] for f in found)
        assert client.post('/api/contacts/searches', json={'id':'search1','provider':'mock','polygon':POLYGON}).status_code == 202
        assert len(client.get('/api/contacts/overview').json()['searches']) == 1
        assert client.post('/api/contacts/searches', json={'id':'search1','provider':'osm','polygon':POLYGON}).status_code == 409
        assert client.post('/api/contacts/searches', json={'id':'berlin','polygon':[[52.5,13.4],[52.6,13.4],[52.6,13.5]]}).status_code == 422


def test_approval_and_source_bound_report(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    database=tmp_path/'db'
    with TestClient(create_app(database)) as client:
        f=next(f for f in search(client) if f['contact'] and not f['discovery']['listed_closed'])
        assert client.post(f"/api/contacts/{f['id']}/approve",json={'phone':'+16195559999'}).status_code==422
        s=client.post(f"/api/contacts/{f['id']}/approve",json={'phone':f['contact']}).json()
        assert s['status']=='approved' and not s['transcript']
        again=client.post(f"/api/contacts/{f['id']}/approve",json={'phone':f['contact']}).json(); assert again['id']==s['id']
        prefix='/api/contacts/sessions/'+s['id']
        payload={'summary':'Two people need transport','source_quote':'Two people need transport','reception_confirmed':True,'needs':[{'description':'Accessible transport','people_count':2}]}
        assert client.post(prefix+'/report',json=payload).status_code==409
        # Model the browser transport's connection independently of remote ElevenLabs.
        from app.contacts import put
        s.update(status='connected',mode='browser_mock');put(client.app.state.db,'contact_sessions',s)
        assert client.post(prefix+'/report',json=payload).status_code==422
        text='Yes, I am reception. Two people need transport'
        client.post(prefix+'/transcript',json={'id':'u1','role':'user','text':text})
        client.post(prefix+'/transcript',json={'id':'u1','role':'user','text':text})
        r=client.post(prefix+'/report',json=payload);assert r.status_code==200,r.text
        assert client.post(prefix+'/report',json=payload).json()['history']==[]
        need=client.get('/api/contacts/needs').json()[0]
        assert client.get('/api/dashboard/context').json()['reported_needs'][0]['session_id']==s['id']
        assert need['reported_by']==f['name'] and need['session_id']==s['id'] and need['mock'] and not need['reception_verified']
        assert client.post(prefix+'/verify-reception',json={}).status_code==200
        assert client.get('/api/contacts/needs').json()[0]['reception_verified']
        client.post(prefix+'/end',json={'status':'completed'})
        assert len(client.get('/api/contacts/overview').json()['sessions'][0]['transcript'])==1
    with TestClient(create_app(database)) as client:
        assert client.get('/api/contacts/overview').json()['sessions'][0]['status']=='completed'
        assert len(client.get('/api/contacts/needs').json())==1


def test_cancel_and_restart_do_not_claim_contact(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    database=tmp_path/'db'
    with TestClient(create_app(database)) as client:
        f=next(f for f in search(client) if f['contact'] and not f['discovery']['listed_closed'])
        s=client.post(f"/api/contacts/{f['id']}/approve",json={'phone':f['contact']}).json()
        prefix='/api/contacts/sessions/'+s['id']
        assert client.post(prefix+'/end',json={'status':'cancelled'}).json()['status']=='cancelled'
        assert client.post(prefix+'/simulate',json={}).status_code==409
        assert not client.get('/api/contacts/needs').json()
        from app.contacts import put
        s.update(id='interrupted',status='connecting');put(client.app.state.db,'contact_sessions',s)
    with TestClient(create_app(database)) as client:
        assert client.get('/api/contacts/overview').json()['sessions'][0]['status']=='interrupted'


def test_scripted_call_and_report_correction(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    with TestClient(create_app(tmp_path/'db')) as client:
        f=next(f for f in search(client) if f['contact'] and not f['discovery']['listed_closed'])
        s=client.post(f"/api/contacts/{f['id']}/approve",json={'phone':f['contact']}).json()
        prefix='/api/contacts/sessions/'+s['id']
        assert client.post(prefix+'/simulate',json={}).status_code==200
        for _ in range(70):
            state=client.get('/api/contacts/overview').json()
            if state['sessions'][0]['status']=='completed':break
            time.sleep(.1)
        assert state['sessions'][0]['status']=='completed'
        assert state['reports'][0]['source']=='scripted_mock'
        assert state['reports'][0]['content']['needs'][0]['people_count']==2
        client.post(prefix+'/verify-reception',json={})
        assert client.get('/api/contacts/needs').json()[0]['reception_verified']
        text='Correction: three people need transport.'
        client.post(prefix+'/transcript',json={'id':'correction','role':'user','text':text})
        response=client.post(prefix+'/report',json={'summary':text,'source_quote':text,'reception_confirmed':True,'needs':[{'description':'Wheelchair transport','people_count':3}]})
        assert response.status_code==200
        assert len(response.json()['history'])==1
        needs=client.get('/api/contacts/needs').json()
        assert len(needs)==1 and needs[0]['people_count']==3 and not needs[0]['reception_verified']
        assert client.get('/api/contacts/overview').json()['reviews']==[]
