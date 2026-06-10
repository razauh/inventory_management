import os
import sys
from pathlib import Path
from constants import DATA_DIR, DB_FILE_NAME

BASE_DIR = Path(__file__).resolve().parent


def _default_data_path() -> Path:
    if getattr(sys, "frozen", False):
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Al Husnain"
        return Path.home() / "AppData" / "Local" / "Al Husnain"
    return BASE_DIR / DATA_DIR


DATA_PATH = _default_data_path()
DB_PATH = DATA_PATH / DB_FILE_NAME

# ensure data dir exists early
DATA_PATH.mkdir(parents=True, exist_ok=True)
