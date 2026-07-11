import inspect, sys
from NorenRestApiPy.NorenApi import NorenApi
print('NorenApi file:', NorenApi.__file__)
print('source snippet:')
print(inspect.getsource(NorenApi)[:500])