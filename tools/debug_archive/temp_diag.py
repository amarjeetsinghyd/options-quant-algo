import psutil, json, os, sys
status_path = os.path.join('runtime','runtime_status.json')
if os.path.exists(status_path):
    with open(status_path) as f:
        data=json.load(f)
        services=data.get('payload',{}).get('services',{})
        print('Shadow status dict:', services.get('shadow_service'))
else:
    print('status file missing')
# list processes containing shadow_service.py
found=False
for p in psutil.process_iter(['pid','cmdline']):
    cmd = p.info['cmdline']
    if cmd and any('shadow_service.py' in part for part in cmd):
        print('Found shadow process PID', p.info['pid'])
        found=True
if not found:
    print('No shadow process found')