"""Load only endless tuna's optional .env; process environment takes precedence."""
from pathlib import Path
from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parents[2] / '.env'
load_dotenv(ENV_FILE, override=False)
