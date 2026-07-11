import os
for var in ['SHOONYA_2FA','SHOONYA_VENDOR_CODE','SHOONYA_API_SECRET','SHOONYA_IMEI']:
    print(var, os.getenv(var))