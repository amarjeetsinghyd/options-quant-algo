import os
import zipfile
import shutil
from datetime import datetime
from pathlib import Path
# The cloud backup service optionally integrates with Google Drive. These
# dependencies are heavy and not required for the core test suite. Import them
# lazily and tolerate their absence so that the module can be imported on a
# minimal development environment.
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except Exception:  # pragma: no cover – optional dependency missing
    Request = Credentials = InstalledAppFlow = build = MediaFileUpload = None

from src.utils.logger import get_logger
from src.config.engineering_config import DATA_DIR

logger = get_logger("cloud_backup")

SCOPES = ['https://www.googleapis.com/auth/drive.file']
CREDS_FILE = os.path.join(os.path.dirname(DATA_DIR), "src", "config", "credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(DATA_DIR), "src", "config", "token.json")

def create_backup_zip():
    today_str = datetime.now().strftime("%d%m%Y")
    zip_path = os.path.join(DATA_DIR, f"backup_{today_str}.zip")
    
    logger.info(f"Creating backup zip at {zip_path}...")
    project_root = os.path.dirname(DATA_DIR)
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
        # 1. Backup Data Directory
        for root, dirs, files in os.walk(DATA_DIR):
            for file in files:
                # Skip the heavy dictionary file and the zip itself
                if file == "OpenAPIScripMaster.json" or file.endswith(".zip"):
                    continue
                
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, project_root)
                zipf.write(abs_path, rel_path)
                
        # 2. Backup Source Directory (Code)
        src_dir = os.path.join(project_root, "src")
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                # Skip compiled python files
                if "__pycache__" in root or file.endswith(".pyc"):
                    continue
                
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, project_root)
                zipf.write(abs_path, rel_path)
                
    logger.info("Zip created successfully with both data/ and src/ directories.")
    return zip_path

def authenticate_drive():
    """Authenticate with Google Drive if the required libraries are available.

    If the optional Google dependencies are missing, this function returns ``None``
    and the caller will skip the upload step. This allows the module to be
    imported and used in environments where Google APIs are not installed (e.g.
    the CI test environment).
    """
    if any(dep is None for dep in (Request, Credentials, InstalledAppFlow)):
        logger.debug("Google Drive libraries not available – skipping authentication.")
        return None

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"Could not refresh token: {e}")
                creds = None

        if not creds:
            if not os.path.exists(CREDS_FILE):
                logger.error("credentials.json not found! Cannot backup to Google Drive.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return creds

def get_or_create_folder(service, folder_name, parent_id=None):
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
        
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    
    if not files:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]
            
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')
    return files[0].get('id')

def upload_to_drive(file_path):
    """Upload the backup zip to Google Drive if authentication succeeded.

    When the Google libraries are unavailable this function becomes a no‑op.
    """
    if any(dep is None for dep in (build, MediaFileUpload)):
        logger.debug("Google Drive upload libraries missing – skipping upload.")
        return

    creds = authenticate_drive()
    if not creds:
        return

    try:
        service = build("drive", "v3", credentials=creds)
        file_name = os.path.basename(file_path)

        # Build Folder Hierarchy: Quant_Algo_Backups / YYYY / Month
        now = datetime.now()
        root_folder_id = get_or_create_folder(service, "Quant_Algo_Backups")
        year_folder_id = get_or_create_folder(service, now.strftime("%Y"), root_folder_id)
        month_folder_id = get_or_create_folder(service, now.strftime("%B"), year_folder_id)

        file_metadata = {"name": file_name, "parents": [month_folder_id]}
        media = MediaFileUpload(file_path, mimetype="application/zip", resumable=True)

        logger.info(
            f"Uploading {file_name} to Google Drive (Quant_Algo_Backups/{now.strftime('%Y/%B')})..."
        )
        file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        logger.info("Upload complete! File ID: %s", file.get("id"))

    except Exception as e:
        logger.error("Google Drive Upload Error: %s", e)

def run_backup():
    try:
        logger.info("Starting automated cloud backup...")
        
        # Cleanup any orphan zip files from previous failed runs
        for old_zip in Path(DATA_DIR).glob("backup_*.zip"):
            old_zip.unlink()
            logger.info(f"Cleaned up orphan zip: {old_zip.name}")
        
        zip_path = create_backup_zip()
        upload_to_drive(zip_path)
        
        # Cleanup local zip after successful upload
        if os.path.exists(zip_path):
            os.remove(zip_path)
            logger.info("Cleaned up local zip file.")
            
        logger.info("Cloud backup process finished.")
    except Exception as e:
        logger.error(f"Backup process failed: {e}")

def run_scheduler():
    logger.info("Cloud Backup Scheduler started.")
    # Run once on boot
    run_backup()
    
    # Then sleep forever (or run daily). Since we restart the whole system daily via PM2/cron, 
    # sleeping indefinitely here prevents the supervisor from restarting us aggressively.
    while True:
        import time
        time.sleep(86400) # Sleep for 24 hours

if __name__ == "__main__":
    run_scheduler()
