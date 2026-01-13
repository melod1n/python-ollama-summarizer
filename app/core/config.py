import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


IN_DOCKER = env_bool("IN_DOCKER", False)

# Base dir for local runs: directory where this file lives
BASE_DIR = Path(__file__).resolve().parent.parent  # app/core/ -> app/
# If your structure differs, adjust accordingly.

DEFAULT_DB_PATH = Path("/db/summaries.db") if IN_DOCKER else (BASE_DIR / "summaries.db")
DEFAULT_LOG_PATH = Path("/logs/summary.log") if IN_DOCKER else (BASE_DIR / "summary.log")

# Allow override from env in both modes
DB_PATH = str(Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH))))
LOG_PATH = str(Path(os.getenv("LOG_PATH", str(DEFAULT_LOG_PATH))))

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.getenv("MODEL_NAME", "mistral")

MAX_TOKENS = env_int("MAX_TOKENS", 6000)
MAX_QUEUE_SIZE = env_int("MAX_QUEUE_SIZE", 5)
CHUNK_MAX_TOKENS = env_int("CHUNK_MAX_TOKENS", 1500)
CHUNK_OVERLAP = env_int("CHUNK_OVERLAP", 200)
