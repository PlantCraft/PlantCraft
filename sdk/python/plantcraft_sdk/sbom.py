"""An SPDX 2.3 JSON SBOM of an app's image, for `make package` when syft is not installed.

Lists what the image really holds, read from inside it: the Debian packages (dpkg) and the
Python distributions (importlib.metadata), each with its version and declared licence.

    plantcraft-app sbom twincraft:0.1.0 > sbom.spdx.json                  # from a built image
    python -m plantcraft_sdk.sbom --here twincraft:0.1.0 > /app/sbom.json  # inside it

``SBOM_CREATED`` (an ISO time) fixes the document's creation time, for reproducible builds.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# Runs inside the image (no pip there): one JSON line per component.
INSIDE = r"""
import json, subprocess
from importlib.metadata import distributions
out = []
try:
    rows = subprocess.run(["dpkg-query", "-W", "-f=${Package}\t${Version}\n"],
                          capture_output=True, text=True, check=True).stdout.splitlines()
    out += [{"type": "deb", "name": n, "version": v} for n, v in (r.split("\t") for r in rows)]
except Exception:
    pass
for dist in distributions():
    meta = dist.metadata
    lic = meta.get("License-Expression") or meta.get("License") or ""
    if len(lic) > 120 or "\n" in lic:
        lic = ""
    out.append({"type": "pypi", "name": meta["Name"], "version": dist.version, "license": lic})
print(json.dumps(out))
"""


def _spdx_id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]", "-", text)


def _created() -> str:
    """``SBOM_CREATED`` when it is a time (the image's build time), else now."""

    given = os.environ.get("SBOM_CREATED", "")
    try:
        moment = datetime.fromisoformat(given.replace("Z", "+00:00"))
    except ValueError:
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(image: str, *, here: bool = False) -> int:
    """Write the SBOM of ``image`` (``name:version``) to standard output."""

    if here:
        command = [sys.executable, "-c", INSIDE]
    else:
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            image,
            "-c",
            INSIDE,
        ]
    found = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )
    components = json.loads(found.stdout)
    name, _, version = image.partition(":")
    packages = [
        {
            "SPDXID": "SPDXRef-image",
            "name": name,
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "licenseConcluded": "Apache-2.0",
        }
    ]
    for item in sorted(components, key=lambda c: (c["type"], c["name"].lower())):
        purl = f"pkg:{item['type']}/{item['name']}@{item['version']}"
        packages.append(
            {
                "SPDXID": f"SPDXRef-{item['type']}-{_spdx_id(item['name'])}-{_spdx_id(item['version'])}",
                "name": item["name"],
                "versionInfo": item["version"],
                "downloadLocation": "NOASSERTION",
                "licenseDeclared": item.get("license") or "NOASSERTION",
                "licenseConcluded": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": purl,
                    }
                ],
            }
        )
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": image,
        "documentNamespace": f"https://github.com/PlantCraft/{_spdx_id(name.rsplit('/', 1)[-1])}"
        f"/sbom/{_spdx_id(image)}",
        "creationInfo": {
            "created": _created(),
            "creators": ["Tool: processcraft-app-sbom"],
        },
        "packages": packages,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-image",
            }
        ]
        + [
            {
                "spdxElementId": "SPDXRef-image",
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": p["SPDXID"],
            }
            for p in packages[1:]
        ],
    }
    json.dump(document, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    here = args[:1] == ["--here"]
    if here:
        args = args[1:]
    if len(args) != 1:
        sys.exit(__doc__)
    sys.exit(main(args[0], here=here))
