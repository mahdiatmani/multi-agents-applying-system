import os
import base64
import mimetypes
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

def get_gmail_service():
    creds = None
    # Token now lives in state/ so it rides along with the mounted state volume
    # in Docker. Legacy project-root location is still checked as a fallback.
    project_root = os.path.join(os.path.dirname(__file__), "..")
    state_token = os.path.join(project_root, "state", "token.json")
    legacy_token = os.path.join(project_root, "token.json")
    token_path = state_token if os.path.exists(state_token) else legacy_token

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Failed to refresh token: {e}. Please delete token.json and re-authenticate.")
                return None
        else:
            print("WARNING: token.json not found or invalid. You must run setup_auth.py locally first!")
            return None

        # Save the credentials for the next run — always to the state/ path so
        # refreshed tokens survive container restarts.
        os.makedirs(os.path.dirname(state_token), exist_ok=True)
        with open(state_token, "w") as token:
            token.write(creds.to_json())

    try:
        service = build("gmail", "v1", credentials=creds)
        return service
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None

def create_gmail_draft(
    to_email: str,
    subject: str,
    body_text: str,
    attachments: list[str] | None = None,
) -> tuple[bool, str]:
    """Returns (success, failure_reason). failure_reason is one of:
       '' (success), 'unauthenticated' (no/expired token.json),
       'http_error: <details>', 'unknown: <details>'.

    attachments: optional list of absolute file paths to attach. Missing or
    unreadable files are logged and skipped — they never fail the whole draft."""
    service = get_gmail_service()
    if not service:
        msg = "Gmail not authenticated (token.json missing or invalid). Run setup_auth.py."
        print(f"[Gmail] {msg}", flush=True)
        return False, "unauthenticated"

    try:
        message = EmailMessage()
        message.set_content(body_text)
        message["To"] = to_email
        message["From"] = "me"
        message["Subject"] = subject

        for path in attachments or []:
            if not path or not os.path.exists(path):
                print(f"[Gmail] attachment missing, skipping: {path!r}", flush=True)
                continue
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
                ctype, _ = mimetypes.guess_type(path)
                if not ctype:
                    ctype = "application/octet-stream"
                maintype, subtype = ctype.split("/", 1)
                message.add_attachment(
                    data,
                    maintype=maintype,
                    subtype=subtype,
                    filename=os.path.basename(path),
                )
                print(f"[Gmail] attached {os.path.basename(path)} ({len(data)} bytes)", flush=True)
            except Exception as exc:
                print(f"[Gmail] failed to attach {path!r}: {exc}", flush=True)

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"message": {"raw": encoded_message}}

        draft = service.users().drafts().create(userId="me", body=create_message).execute()
        print(f"[Gmail] Draft created. ID: {draft['id']}", flush=True)
        return True, ""
    except HttpError as error:
        print(f"[Gmail] HTTP error creating draft: {error}", flush=True)
        return False, f"http_error: {error}"
    except Exception as exc:
        print(f"[Gmail] Unknown error creating draft: {exc}", flush=True)
        return False, f"unknown: {type(exc).__name__}: {exc}"
