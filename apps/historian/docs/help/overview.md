# Overview

The overview page says whether Historian is collecting and how much it holds.

- **Collector**: running or stopped, with the time of its last heartbeat. Historian archives a
  gap for every signal when the collector stops, so trends never draw a line across downtime.
- **Signals**: how many are collecting, waiting, failing or disabled.
- **Archive**: values archived, bytes on disk and the compression ratio (values read per value
  kept).
- **Sources**: each OPC UA server, its state and its last error.
