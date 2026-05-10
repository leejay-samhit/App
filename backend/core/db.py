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

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
