import inspect, json, sys
from NorenRestApiPy.NorenApi import NorenApi
print('Attributes of NorenApi class:')
print([a for a in dir(NorenApi) if not a.startswith('_')])
print('\nSource of __init__:')
print(inspect.getsource(NorenApi.__init__))