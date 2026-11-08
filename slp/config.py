"""Shared locations, independent of the working directory and module folders."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get('SLP_DATA') or PROJECT_ROOT / 'data').expanduser().resolve()
DB_PATH = Path(os.environ.get('SLP_DB') or PROJECT_ROOT / 'slp.duckdb').expanduser().resolve()
RUNTIME_DIR = Path(os.environ.get('SLP_RUNTIME') or PROJECT_ROOT / 'runtime').expanduser().resolve()
