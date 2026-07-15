import sys
sys.path.append('C:\\Quant')
from src.broker.adapters.shoonya_adapter import ShoonyaAdapter
import inspect

adapter = ShoonyaAdapter()
methods = [m[0] for m in inspect.getmembers(adapter.api, predicate=inspect.ismethod)]
print("Checking Shoonya API methods...")
found = False
for m in methods:
    if 'index' in m.lower() or 'constit' in m.lower() or 'list' in m.lower() or 'watch' in m.lower() or 'weight' in m.lower():
        print("Found matching method:", m)
        found = True

if not found:
    print("No methods found for indices, constituents, lists, or watchlists.")
