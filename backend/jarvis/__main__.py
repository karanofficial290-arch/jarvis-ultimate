"""Run the backend: python -m jarvis [--host 127.0.0.1] [--port 8765]"""
import argparse
import logging

import uvicorn

from .app import create_app
from .config import load_dotenv


def main() -> None:
    ap = argparse.ArgumentParser(description="JARVIS Ultimate AI backend")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (keep 127.0.0.1 behind a TLS proxy)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--env-file", default=".env", help="optional KEY=VALUE file; real env vars take precedence")
    a = ap.parse_args()
    load_dotenv(a.env_file)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(), host=a.host, port=a.port, proxy_headers=True, log_level="info")


if __name__ == "__main__":
    main()
