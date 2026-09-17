#!/usr/bin/env python
import subprocess
import sys
import time
import urllib.request
import json

# Start the server
proc = subprocess.Popen(
    [sys.executable, 'main.py'], 
    cwd=r'C:\Users\L390 YOGA\WhatsAppGenerator',
    stdout=subprocess.PIPE, 
    stderr=subprocess.PIPE
)

print(f'Server started with PID: {proc.pid}')
time.sleep(3)

# Test the main page
try:
    r = urllib.request.urlopen('http://localhost:8000/')
    print('=== Main Page ===')
    print(r.read().decode()[:500])
except Exception as e:
    print(f'Error main page: {e}')

# Test generate number
try:
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
    print('=== Generate Number ===')
    print(result[:400])
except Exception as e:
    print(f'Error generate number: {e}')

# Test cities endpoint
try:
    r = urllib.request.urlopen('http://localhost:8000/api/cities?country=US')
    result = r.read().decode()
    print('=== Cities ===')
    print(result[:300])
except Exception as e:
    print(f'Error cities: {e}')

# Wait then stop
time.sleep(2)
proc.terminate()
print('=== Server stopped ===')