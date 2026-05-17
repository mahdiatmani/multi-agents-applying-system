import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

def main():
    print("Starting Gmail OAuth Authentication Setup...")
    creds_path = "credentials.json"
    # Write token into state/ so the Docker container (which mounts ./state)
    # picks it up without any extra volume config.
    state_dir = os.path.join(os.path.dirname(__file__), "state")
    os.makedirs(state_dir, exist_ok=True)
    token_path = os.path.join(state_dir, "token.json")

    if not os.path.exists(creds_path):
        print(f"ERROR: {creds_path} not found in this directory. Please download it from Google Cloud Console.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    # This will open a browser window for you to log in
    creds = flow.run_local_server(port=0)

    with open(token_path, "w") as token:
        token.write(creds.to_json())

    print(f"\nSUCCESS! {token_path} has been generated.")
    print("You can now run the Docker container. The bot will use this token to authenticate automatically.")

if __name__ == "__main__":
    main()
