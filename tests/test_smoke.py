from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    r = client.get('/api/health')
    assert r.status_code == 200
    assert r.json()['database'] == 'SQLITE'

def test_login_and_dashboard():
    r = client.post('/api/auth/login', data={'email':'citizen@civiccare.local','password':'Citizen@123'})
    assert r.status_code == 200
    token = r.json()['token']
    r2 = client.get('/api/dashboard', headers={'Authorization':f'Bearer {token}'})
    assert r2.status_code == 200
    assert 'stats' in r2.json()

def test_public_summary():
    r = client.get('/api/public/summary')
    assert r.status_code == 200
    assert 'complaints' in r.json()
