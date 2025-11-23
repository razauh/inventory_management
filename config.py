from pathlib import Path
from constants import DATA_DIR, DB_FILE_NAME

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / DATA_DIR
DB_PATH = DATA_PATH / DB_FILE_NAME

# ensure data dir exists early
DATA_PATH.mkdir(parents=True, exist_ok=True)
