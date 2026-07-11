from NorenRestApiPy.NorenApi import NorenApi
api = NorenApi(host='https://api.shoonya.com/NorenWClientTP/', websocket='wss://api.shoonya.com/NorenWSTP/')
print('has session?', hasattr(api, 'session'))
print('dir:', [a for a in dir(api) if not a.startswith('_')])