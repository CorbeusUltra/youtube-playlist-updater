import os
from pathlib import Path

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .youtube import YouTube

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def connect(directory: Path, port: int, interactive: bool, notify=print) -> YouTube:
    """Shared OAuth implementation independent of playlists and terminal rendering."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = directory / "token.json"
    creds, changed = None, False
    if token.exists():
        try:
            creds = Credentials.from_authorized_user_file(token, SCOPES)
            if not creds.valid and creds.refresh_token:
                creds.refresh(Request())
                changed = True
        except (RefreshError, ValueError):
            creds = None
        except TransportError as exc:
            raise RuntimeError("Cannot reach Google to refresh authentication. Check your connection and retry.") from exc
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("Google authentication required. Run with --check and the same --config/--profile selection in an interactive terminal to sign in.")
        secret = directory / "credentials.json"
        if not secret.exists():
            raise RuntimeError(f"Missing OAuth credentials: place the Desktop app client file at {secret}.")
        notify("Google authentication required: authorize the application in your browser.")
        flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
        creds = flow.run_local_server(port=port, timeout_seconds=300, authorization_prompt_message="Open this link if the browser does not open: {url}", success_message="Authentication successful. Close this tab and return to your terminal.")
        if creds is None:
            raise RuntimeError("Google authentication was not completed. Run the application again to retry.")
        changed = True
    if changed:
        staged = directory / "token.next.json"
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(staged, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(creds.to_json())
            stream.flush()
            os.fsync(stream.fileno())
        staged.replace(token)
    if token.exists():
        os.chmod(token, 0o600)
    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=30))
    return YouTube(build("youtube", "v3", http=http, cache_discovery=False))
