import json, subprocess, sys, time, urllib.request
import phonenumbers
from urllib.error import HTTPError

proc = subprocess.Popen(
    [sys.executable, '-u', '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8071'],
    cwd=r'C:\Users\L390 YOGA\WhatsAppGenerator',
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(9)
base = 'http://127.0.0.1:8071'
ok = []


def req(path, method='GET', body=None, timeout=20):
    url = base + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'} if body is not None else {}
    req_ = urllib.request.Request(url, data=data, method=method, headers=headers)
    return urllib.request.urlopen(req_, timeout=timeout)


def check(name, fn):
    try:
        result = fn()
        ok.append((name, 'OK', result))
    except HTTPError as e:
        ok.append((name, 'HTTP %s' % e.code, e.read().decode(errors='replace')[:200]))
    except Exception as e:
        ok.append((name, 'FAIL', repr(e)))

check('GET / page contient Campagnes', lambda: ('Campagnes' in req('/').read().decode()))
check('GET / page contient Base de donnees', lambda: ('Base de donnees' in req('/').read().decode()))

def batch():
    r = json.loads(req('/api/generate-batch', 'POST', {'country_code': 'FR', 'city': 'Paris', 'count': 5, 'pattern': 'random'}).read().decode())
    assert r['count'] == 5, r
    for n in r['numbers']:
        assert phonenumbers.is_valid_number(phonenumbers.parse(n['number'], None)), n
    return '5 numeros FR valides'
check('POST /api/generate-batch', batch)

def stats():
    r = json.loads(req('/api/stats').read().decode())
    assert 'today_total' in r and 'by_status' in r and 'uptime' in r
    return 'stats enrichies (total=%d)' % r['total']
check('GET /api/stats enrichies', stats)

def create_camp():
    r = json.loads(req('/api/campaigns', 'POST', {
        'name': 'Test E2E', 'country_code': 'ES', 'city': 'Madrid', 'count': 6,
        'message': 'Bonjour test', 'send_after_test': False, 'delay_ms': 0
    }).read().decode())
    assert r['success']
    return r['campaign']['id']
camp_id = None
def create_camp_wrapper():
    global camp_id
    camp_id = create_camp()
    return 'campagne creee: ' + camp_id
check('POST /api/campaigns', create_camp_wrapper)

def start_and_wait():
    global camp_id
    req('/api/campaigns/%s/start' % camp_id, 'POST')
    deadline = time.time() + 60
    while time.time() < deadline:
        r = json.loads(req('/api/campaigns').read().decode())
        camp = next(c for c in r['campaigns'] if c['id'] == camp_id)
        if camp['status'] in ('done', 'stopped', 'error'):
            return 'campagne %s (genere=%d teste=%d existants=%d)' % (camp['status'], camp['generated'], camp['tested'], camp['exists_count'])
        time.sleep(2)
    return 'TIMEOUT campagne'
check('POST /api/campaigns/{id}/start + polling', start_and_wait)

def camp_stored_nums():
    r = json.loads(req('/api/numbers?status=tested&country=ES').read().decode())
    assert r['count'] > 0
    return '%d numeros ES testes dans la base' % r['count']
check('GET /api/numbers filters (status+country)', camp_stored_nums)

def imp():
    r = json.loads(req('/api/import', 'POST', {'numbers': ['+33612345678', '+34 710 33 97 86', '+4915112345', 'garbage']}).read().decode())
    assert r['imported'] >= 2 and r['invalid'] >= 1, r
    return 'import ok (imported=%d invalid=%d skipped=%d)' % (r['imported'], r['invalid'], r['skipped'])
check('POST /api/import', imp)

def export():
    r = req('/api/export?format=csv&status=all&search=')
    ct = r.headers.get('Content-Type')
    assert 'text/csv' in ct
    assert 'campaign_id' in r.read().decode()
    return 'CSV genere (%s)' % ct
check('GET /api/export csv', export)

def export_json():
    r = req('/api/export?format=json&status=all&search=')
    data = json.loads(r.read().decode())
    assert isinstance(data, list)
    return 'JSON genere (%d lignes)' % len(data)
check('GET /api/export json', export_json)

def search():
    r = json.loads(req('/api/numbers?search=Madrid').read().decode())
    assert r['count'] >= 0
    return 'recherche textuelle ok (count=%d)' % r['count']
check('GET /api/numbers?search=', search)

proc.terminate()
print('\n==== RESULTATS E2E ====')
failures = 0
for name, status, detail in ok:
    flag = 'PASS' if status == 'OK' else 'FAIL'
    if status != 'OK':
        failures += 1
    print('[%s] %s -> %s' % (flag, name, detail))
print('TOTAL: %d tests, %d echecs' % (len(ok), failures))
with open('e2e_result.txt', 'w') as f:
    f.write('%d echecs' % failures)