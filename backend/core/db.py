"""MongoDB client — single source of truth for the db handle."""
from dotenv import load_dotenv
from pathlib import Path
import os

# Load env from /app/backend/.env regardless of cwd
_ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT_DIR / '.env')

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']

# Nov-2026 — production runs against MongoDB Atlas, which is a network hop away
# instead of a unix socket. The driver defaults (no socket timeout, 30s server
# selection) made long reads — the auto-backup snapshot in particular — die with
# "The read operation timed out" and left the pool half-used. Explicit, generous
# timeouts plus a bounded pool keep slow reads alive and failures fast.
client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=15000,
    connectTimeoutMS=15000,
    socketTimeoutMS=180000,      # long analytics/backup reads need room
    maxPoolSize=50,
    minPoolSize=1,
    retryWrites=True,
    retryReads=True,
    compressors="zlib",          # Atlas egress is billed; JSON compresses well
)
db = client[DB_NAME]
