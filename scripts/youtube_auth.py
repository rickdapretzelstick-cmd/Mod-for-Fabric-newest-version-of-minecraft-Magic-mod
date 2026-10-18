"""One-time YouTube OAuth. Opens Google's own consent page in your browser; the token is stored in secrets/ (git-ignored).
You never give this program your Google password."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from google_auth_oauthlib.flow import InstalledAppFlow
from factory import publish

if not publish.CLIENT.exists():
    sys.exit(f"Missing {publish.CLIENT}\nCreate an OAuth 'Desktop app' client at https://console.cloud.google.com/apis/credentials (enable YouTube Data API v3) and save the JSON there.")
flow = InstalledAppFlow.from_client_secrets_file(str(publish.CLIENT), ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"])
creds = flow.run_local_server(port=0)
publish.TOKEN.write_text(creds.to_json())
print("Saved", publish.TOKEN)
