import os
from dotenv import load_dotenv
from app.database.models import (
    OAuthProvider,
)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://uno_user:uno_password@localhost:5432/uno_db")

OAUTH_CONFIG = {
    OAuthProvider.GOOGLE: {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        # ... rest of config
    },
    # ... other providers
}