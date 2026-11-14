import atexit
import logging
import os

import pymongo
from dotenv import load_dotenv
from pymongo.errors import PyMongoError

load_dotenv()

logger = logging.getLogger("api")

url = os.getenv("MONGODB_URI")
if not url:
    raise RuntimeError("MONGODB_URI is not set. Copy .env.example to .env and fill it in.")

# One client for the whole process. PyMongo keeps its own connection pool,
# so every request reuses these connections instead of opening new ones.
client = pymongo.MongoClient(
    url,
    maxPoolSize=int(os.getenv("MONGODB_MAX_POOL_SIZE", "50")),
    maxIdleTimeMS=60_000,
    serverSelectionTimeoutMS=int(os.getenv("MONGODB_TIMEOUT_MS", "5000")),
    connectTimeoutMS=int(os.getenv("MONGODB_TIMEOUT_MS", "5000")),
    socketTimeoutMS=20_000,
    waitQueueTimeoutMS=5_000,
    retryWrites=True,
    tz_aware=True,
    appname="notesphere",
)
db = client[os.getenv("MONGODB_DATABASE", "notesphere")]


def get_database():
    return db


def get_collection(name: str):
    # Reads the module level `db` on every call, so tests can point it
    # to a separate test database: db_connection.db = client["notesphere_test"]
    return db[name]


def check_connection() -> bool:
    try:
        client.admin.command("ping")
        return True
    except PyMongoError:
        logger.error("MongoDB ping failed")
        return False


def close_connection() -> None:
    client.close()


atexit.register(close_connection)