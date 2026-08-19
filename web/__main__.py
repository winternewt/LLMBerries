"""`uv run python -m web` — serve the observatory.

Never run this under a reloader: a live game runs on a worker thread inside this
process, and a reload kills it mid-hour with the run directory half-written.
"""

import logging
import sys

import uvicorn
from dotenv import load_dotenv

from web.app import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    load_dotenv()
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
