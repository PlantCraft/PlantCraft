"""Download the embedding model named in deploy/embedding-model.lock and check each file's hash.

    python fetch_model.py embedding-model.lock /models/multilingual-e5-small

Run at image build only (Dockerfile, stage "model"); the app never downloads anything.

A lock whose lines are all "unpinned", or a build machine that cannot reach the model's host,
builds the image without the model: the folder stays empty, the app searches by words only and
says so (Search, Reading queue). A file that downloads with another hash stops the build: an
unchecked file never goes into the image.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path


def main(lock: str, folder: str) -> int:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    lines = [
        line.split()
        for line in Path(lock).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if all(expected == "unpinned" for expected, _name, _url in lines):
        print("embedding model unpinned: built without it, search by words only", file=sys.stderr)
        return 0
    failed = False
    for expected, name, url in lines:
        digest = hashlib.sha256()
        try:
            with (
                urllib.request.urlopen(url, timeout=120) as answer,
                (out / name).open("wb") as file,
            ):
                while chunk := answer.read(1 << 20):
                    digest.update(chunk)
                    file.write(chunk)
        except OSError as error:  # no route to the host (an offline build machine)
            for _expected, other, _url in lines:
                (out / other).unlink(missing_ok=True)
            print(f"{name}: not downloaded ({error}): built without the model", file=sys.stderr)
            return 0
        got = digest.hexdigest()
        if got != expected:
            print(f"{name}: sha256 {got}, the lock says {expected}", file=sys.stderr)
            failed = True
        else:
            print(f"{name}: {got} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
