import sys
sys.path.append('C:\\Quant')
from src.services.brain_service import BrainService
try:
    b = BrainService()
    print("SUCCESS")
except Exception as e:
    import traceback
    traceback.print_exc()
