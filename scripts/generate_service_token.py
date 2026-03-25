"""Generate a secure random token for inter-service authentication (X-Service-Token)."""

import secrets

if __name__ == "__main__":
    token = secrets.token_urlsafe(48)
    print("Generated X-Service-Token (add to .env):\n")
    print(f"X_SERVICE_TOKEN={token}")
