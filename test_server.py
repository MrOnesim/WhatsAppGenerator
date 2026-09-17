import subprocess
import sys
import time

# Start the server
proc = subprocess.Popen(
    [sys.executable, 'main.py'], 
    cwd=r'C:\Users\L390 YOGA\WhatsAppGenerator',
    stdout=subprocess.PIPE, 
    stderr=subprocess.PIPE
)

print(f'Server started with PID: {proc.pid}')
time.sleep(3)

# Test the server
try:
    import urllib.request
    r = urllib.request.urlopen('http://localhost:8000/')
    print('Server is running!')
    print(r.read().decode()[:500])
except Exception as e:
    print(f'Error connecting: {e}')

# Test the generate number endpoint
try:
    import urllib.request
    import json
    data = json.dumps({
        'country_code': 'US',
        'city': 'New York',
        'pattern': 'random'
    }).encode()
    req = urllib.request.Request(
        'http://localhost:8000/api/generate-number',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    r = urllib.request.urlopen(req)
    result = r.read().decode()
    print('Generate number result:', result[:300])
except Exception as e:
    print(f'Error generating number: {e}')

# Wait a bit then stop
time.sleep(2)
proc.terminate()
print('Server stopped')