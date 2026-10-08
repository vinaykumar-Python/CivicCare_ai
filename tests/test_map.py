from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def token():
    r = client.post('/api/auth/login', data={'email':'admin@civiccare.local','password':'Admin@123','role':'admin','department':'Administration'})
    assert r.status_code == 200
    return r.json()['token']

def test_map_layers_and_area_analysis():
    h={'Authorization':'Bearer '+token()}
    r=client.get('/api/map/issues',headers=h)
    assert r.status_code == 200
    data=r.json()
    assert 'issues' in data and data['issues']
    assert 'not live traffic' in data['note'].lower()
    a=client.get('/api/map/area?latitude=12.9716&longitude=77.5946&radius_km=5',headers=h)
    assert a.status_code == 200
    body=a.json()
    assert {'overall_risk','accidents','complaints','traffic_risk','top_cause'}.issubset(body)
