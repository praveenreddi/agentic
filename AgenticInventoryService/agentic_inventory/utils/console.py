import os
import argparse
import configparser
import getpass
import requests
from dotenv import load_dotenv
from msal import PublicClientApplication


# Azure AD token validation settings
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")

# Flag to indicate if authentication is enabled
AUTH_ENABLED = bool(TENANT_ID and CLIENT_ID)

AUTHORITY_URL = f"https://login.microsoftonline.com/{TENANT_ID}"


def get_url_and_headers(env: str):
    """
    Reads the configuration file (console.config) to obtain the URL and API key
    for the selected environment, then returns them along with headers.
    """
    config = configparser.ConfigParser()
    config.read("console.config")
    try:
        url = config[env]["url"]
        key = config[env]["key"]
    except KeyError as e:
        raise Exception(f"Configuration for environment '{env}' is missing required key: {e}")

    correlation_id = f"console_{getpass.getuser()}"
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "X_HGV_TransactionId": correlation_id,
        "correlationId": correlation_id,
        "Content-Type": "application/json",
    }
    return url, headers


def parse_args():
    """
    Parses command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Command-line interface for Agentic Inventory Service")
    parser.add_argument(
        "--env",
        choices=["local", "dev", "qat", "stg", "prd"],
        default="local",
        help="Select environment (default: local)",
    )
    parser.add_argument("--user-id", default="console_user", help="User ID for the session")
    parser.add_argument("--list-sessions", action="store_true", help="List all sessions for the user")
    args, unknown = parser.parse_known_args()

    if unknown:
        raise Exception("Unknown arguments: " + str(unknown))

    return args


def get_user_sessions(url: str, headers: dict, user_id: str) -> list:
    """Get all sessions for a user."""
    sessions_url = f"{url}/api/users/{user_id}/sessions"
    response = requests.get(sessions_url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to get sessions: {response.status_code} {response.text}")


def create_session(url: str, headers: dict, user_id: str) -> str:
    """Create a new chat session."""
    session_url = f"{url}/api/users/{user_id}/sessions"
    response = requests.post(session_url, headers=headers)
    if response.status_code == 201:
        return response.json()["id"]
    else:
        raise Exception(f"Failed to create session: {response.status_code} {response.text}")


def send_message(url: str, headers: dict, user_id: str, session_id: str, message: str) -> dict:
    """Send a message to the chat session."""
    message_url = f"{url}/api/users/{user_id}/sessions/{session_id}/messages"
    payload = {"question": message}
    response = requests.post(message_url, json=payload, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to send message: {response.status_code} {response.text}")


def get_session_messages(url: str, headers: dict, user_id: str, session_id: str) -> list:
    """Get all messages from a chat session."""
    messages_url = f"{url}/api/users/{user_id}/sessions/{session_id}/messages"
    response = requests.get(messages_url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to get messages: {response.status_code} {response.text}")


def get_auth_headers():
    if AUTH_ENABLED:
        app = PublicClientApplication(CLIENT_ID, authority=AUTHORITY_URL)

        flow = app.initiate_device_flow(scopes=["User.Read"])
        if "user_code" not in flow:
            raise Exception("Failed to initiate device code flow")

        print(f"Please go to {flow['verification_uri']} and enter the code {flow['user_code']} to authenticate.")

        token = app.acquire_token_by_device_flow(flow)
        if "access_token" not in token:
            raise Exception("Failed to acquire token")

        auth_headers = {
            "Authorization": f"Bearer {token['access_token']}",
            "Content-Type": "application/json",
        }
    else:
        auth_headers = {}
        print("Azure AD authentication is DISABLED! Running in unsecured mode.")

    return auth_headers


def main():
    # Load environment variables
    load_dotenv()
    args = parse_args()
    env = args.env
    user_id = args.user_id

    auth_headers = get_auth_headers()

    # Get API configuration
    url, headers = get_url_and_headers(env)

    headers.update(auth_headers)

    try:
        # If --list-sessions flag is set, list all sessions and exit
        if args.list_sessions:
            sessions = get_user_sessions(url, headers, user_id)
            for session in sessions:
                print(f"{session['id']}: {session.get('title', 'Untitled')}")
            return

        # Create a new session
        session_id = create_session(url, headers, user_id)

        while True:
            # Get user input
            message = input("\nEnter your message (or blank to exit): ").strip()
            if not message:
                break

            # Send message and get response
            response = send_message(url, headers, user_id, session_id, message)
            print(response["answer"])

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
