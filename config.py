import os
import sys
from pathlib import Path
from constants import APP_DATA_DIR_NAME, APP_LEGACY_DATA_DIR_NAME, DATA_DIR, DB_FILE_NAME

BASE_DIR = Path(__file__).resolve().parent


def _default_data_path() -> Path:
    if getattr(sys, "frozen", False):
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            root = Path(local_app_data)
        else:
            root = Path.home() / "AppData" / "Local"
        current = root / APP_DATA_DIR_NAME
        legacy = root / APP_LEGACY_DATA_DIR_NAME
        if not current.exists() and legacy.exists():
            return legacy
        return current
    return BASE_DIR / DATA_DIR


DATA_PATH = _default_data_path()
DB_PATH = DATA_PATH / DB_FILE_NAME

# ensure data dir exists early
DATA_PATH.mkdir(parents=True, exist_ok=True)
