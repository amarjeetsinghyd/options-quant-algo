from NorenRestApiPy.NorenApi import NorenApi
import inspect

api = NorenApi(host='http://dummy.com', websocket='ws://dummy.com')
methods = [m[0] for m in inspect.getmembers(api, predicate=inspect.ismethod)]
print("Methods available:")
for m in methods:
    if 'index' in m.lower() or 'constit' in m.lower() or 'list' in m.lower() or 'watch' in m.lower() or 'weight' in m.lower() or 'scrip' in m.lower():
        print("-", m)
