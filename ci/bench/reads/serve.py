"""Run the Historian API over the bench database, with a FakePlantCraft for tokens.

    python serve.py --db URL --port 8100        # writes ../token.txt (admin, 24 h)
"""
import argparse, logging, os
import uvicorn
from plantcraft_sdk.testing import BASE_URL, FakePlantCraft
from histcraft.api.app import create_app
from histcraft.api.runtime import Runtime
from histcraft.config import Settings

ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True)
ap.add_argument("--port", type=int, default=8100)
ap.add_argument("--read-values", type=int, default=4_000_000)
a = ap.parse_args()
users = {"admin": {"name": "Admin", "level": "admin", "apps": {"histcraft": "editor", "linkcraft": "editor"}}}
fake = FakePlantCraft(users=users)
with open(os.path.join(os.path.dirname(__file__), "..", "token.txt"), "w") as f:
    f.write(fake.token("admin", ttl=86400 * 3))
settings = Settings(processcraft_url=BASE_URL, data_dir=__import__("pathlib").Path("/home/user/bench/var"), collector="off",
                    database_url=a.db, read_values=a.read_values)
rt = Runtime(settings, verifier=fake.verifier("histcraft"), http_client=fake.http_client())
logging.basicConfig(level=logging.WARNING)
uvicorn.run(create_app(rt), host="127.0.0.1", port=a.port, log_level="warning", access_log=False)
