"""Fetch the Skoltech Anomaly Benchmark (SKAB) into ``oracles/skab/`` at a pinned commit.

Source: Katser, I. D., Kozitsin, V. O. (2020), Skoltech Anomaly Benchmark (SKAB), Kaggle,
https://doi.org/10.34740/KAGGLE/DSV/1693952, published at https://github.com/waico/SKAB. A pump
and water circuit test bench: eight sensors once a second, one experiment per file (a valve
closed at the inlet or outlet, leaks, rotor imbalance, cavitation), each sample labelled
``anomaly`` (0/1) and ``changepoint`` (0/1).

The data is GPL-3.0, so it is never committed (``/oracles/`` is gitignored): CI and developers
download it here, and every file is checked against the sha256 pinned below. A new commit is a
new pin.

    python tests/oracles/fetch_skab.py                    # download the pinned files
    python tests/oracles/fetch_skab.py --source DIR      # same, from a clone's data/ folder
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.request
from pathlib import Path

COMMIT = "b2c0d46c2971dcbfe71e26087b6d231998bb91c2"  # waico/SKAB master, 2024-08-11 (v0.9)
URL = f"https://raw.githubusercontent.com/waico/SKAB/{COMMIT}/data/{{path}}"
FILES = {
    "anomaly-free/anomaly-free.csv": "7641a8742957100ef424dd97adfb3eeab27d4d180645fe2b3c49b7f7146ae9a6",
    "other/1.csv": "3beaf861bdfe9b4f4eff8e7567c1dd3f506fbd0ce667fc9399d04bd2dc70623d",
    "other/2.csv": "951c326bf36366fa7615b8f28d22f80b3878036069a690f42b3e223737a6a8d1",
    "other/3.csv": "f3c19a89f74f62a475c246b9263f161f7a734dd88304de803939cebaa55c7ebd",
    "other/4.csv": "56ca23f4eb61d1347d079eb9a35c60a59b8b64e160c00dd0c2ec69e0df0b2a4b",
    "other/5.csv": "7347b326df3a92c0810c69add0e5621939af7a1c1cb4755081d088e72d36920f",
    "other/6.csv": "eb8f05622a62c855040ea358b87be35fb1a4a3720ba0610569bab384db4b6e04",
    "other/7.csv": "1bee14f49bfc817ba2c335fb427baa71153d8f8ab52e72652f15f74e4b77daec",
    "other/8.csv": "12c138ed99c198e0a7ece886fe01bfd16bbdde206fad6c5d74322b6b9d6488d0",
    "other/9.csv": "11c4514b0bc706acff637fea6707ad9258ac878fe9dff3d0b11d2b618d94d8ea",
    "other/10.csv": "72683644f6f17689f619076a66a9ec02cbc0502bd669924c4c33951d1bdad9b0",
    "other/11.csv": "98a2fff3b6516205ae2e12f2dd30d7f08465fe4321a1bd5cf823396985ecb37b",
    "other/12.csv": "b0882efbcf2669223ae78bee61c9f10074a9b2375f0e86b8957ae5ce4aad1e72",
    "other/13.csv": "b3f1da02064d11234836a9fa1a2536bb0d3b6c6998ab60b0b71869b98e94d860",
    "other/14.csv": "c7f361e55397cc9efd4a76b6876111eda79b650d10aeb007342ca5972152eaef",
    "valve1/0.csv": "16af3f71313a23dd33d9b7b8065d836d05c3f9257588881cc7fbe07c076d9dc8",
    "valve1/1.csv": "fe4493bf805baef4e6dfb864094275d8cc2ea80a16b3735e2752b18b6aefd812",
    "valve1/2.csv": "90492413469261886c8896c327241448df5da73fd7739cabfec8dd82de3c0ce4",
    "valve1/3.csv": "cb6afea108eddfd8447307e405f86bbb764b8d8e9130d7849a46e1303e19b8b2",
    "valve1/4.csv": "983aed9dc09991a57911091373c580e1b86d06aa983cd51678f108fd8d709654",
    "valve1/5.csv": "78974991ec87b7f9b9b6b2944f4b525468a9beb36c59b06cd7650d9a15eca14a",
    "valve1/6.csv": "97469c0e0c9c0e0ee5d30794f1f36c6785df5816a112a8b16c59637e8c894685",
    "valve1/7.csv": "ca2c9c6d6fa302c642acec6fbedac495bd12fececeee0a755d45a54e340e0f30",
    "valve1/8.csv": "0c4afb92248b5b35b4c9d734a91ed8318346901f04579074903730569e60416c",
    "valve1/9.csv": "2aa1ae1b2ff505caecda24802b877dc686924bbbeeb7e7db4faa261efb5ed5bd",
    "valve1/10.csv": "ee16be8e4b870c779491e3d1dc9e0ecbfaf29eb013e032abff7a33f2cbbfe2ad",
    "valve1/11.csv": "89660fae4ed5c918db014409bbbc29f498fd99c7e956fab2620d18dea700a973",
    "valve1/12.csv": "90adfa9bc86d4556e6a4ce734436fd5685af79c189cd9828f8df75a7f468ce07",
    "valve1/13.csv": "d6cb6a97437215d3066a87e1fcc5fa4e68017629c043c5315920e3cf1060841c",
    "valve1/14.csv": "5f0bb9bc33c5e6c259263e32e25915c4d24c82b0a94554d48808626da05c1d71",
    "valve1/15.csv": "75cc86ab25d7091eee024739fa06d048753480d5d7d1507077231cab4f1b7a7e",
    "valve2/0.csv": "a6670e7a68c7c6ba62c649bd9d350633e80db624578e9529f2b736ced5e32bde",
    "valve2/1.csv": "b35d27f664eb0851ab73e5eb06633404c7eeaf532edff7e40c68eb9379f2012b",
    "valve2/2.csv": "2c3005cf28b88db715b7f4694e826ff252cba4dbb1eba679b040961f80477e60",
    "valve2/3.csv": "86927555d5c523e587d41500bd5dee4e2468289ec1b988ac17755aeae697d7f8",
}

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "oracles" / "skab"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download(path: str) -> bytes:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(URL.format(path=path), timeout=60) as response:  # noqa: S310 (pinned URL)
                return response.read()
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def fetch(target: Path = TARGET, source: Path | None = None) -> int:
    """Write every pinned file under ``target``; a file already there with the right hash is
    kept. Returns how many files were written."""

    written = 0
    for path, digest in FILES.items():
        destination = target / path
        if destination.exists() and sha256(destination.read_bytes()) == digest:
            continue
        data = (source / path).read_bytes() if source else _download(path)
        if sha256(data) != digest:
            sys.exit(f"{path}: sha256 {sha256(data)} is not the pinned {digest}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, help="a clone's data/ folder instead of the web")
    arguments = parser.parse_args()
    written = fetch(source=arguments.source)
    print(f"SKAB at {COMMIT[:7]}: {len(FILES)} files in {TARGET} ({written} written)")


if __name__ == "__main__":
    main()
