import sys
import os

with open("boot_error.log", "a") as f:
    sys.stdout = f
    sys.stderr = f
    import start_all
    start_all.main()
