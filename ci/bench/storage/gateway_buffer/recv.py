"""Historian's ingest app on a port, with a collector that only writes what it is given."""

import sys

import uvicorn
from histcraft.collector.ingest import ingest_app

OUT = open(sys.argv[2], "a")  # noqa: SIM115 - kept open while the server runs


class Fake:
    def ingest(self, metrics):
        for metric in metrics:
            OUT.write(f"probe n={metric.fields.get('n')} {metric.at_ms}\n")
        OUT.flush()
        return len(metrics)


uvicorn.run(ingest_app(Fake(), "x"), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
