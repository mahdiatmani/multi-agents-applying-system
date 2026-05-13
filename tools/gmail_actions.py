import os
import base64
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

def get_gmail_service():
    creds = None
    # Paths are relative to the root of the project
    token_path = os.path.join(os.path.dirname(__file__), "..", "token.json")
    creds_path = os.path.join(os.path.dirname(__file__), "..", "credentials.json")

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
            
        # Save the credentials for the next run
        with open(token_path, "w") as token:
            token.write(creds.to_json())

    try:
        service = build("gmail", "v1", credentials=creds)
        return service
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None

def create_gmail_draft(to_email: str, subject: str, body_text: str) -> bool:
    service = get_gmail_service()
    if not service:
        print("Failed to obtain Gmail service.")
        return False
        
    try:
        message = EmailMessage()
        message.set_content(body_text)
        message["To"] = to_email
        message["From"] = "me"
        message["Subject"] = subject

        # Encode the message
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"message": {"raw": encoded_message}}
        
        # Create draft via API
        draft = service.users().drafts().create(userId="me", body=create_message).execute()
        print(f"Draft created successfully! Draft ID: {draft['id']}")
        return True
    except HttpError as error:
        print(f"An error occurred creating draft: {error}")
        return False
