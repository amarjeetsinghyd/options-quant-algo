import importlib.util, sys
spec = importlib.util.find_spec('NorenRestApiPy.NorenApi')
print('spec origin:', spec.origin)