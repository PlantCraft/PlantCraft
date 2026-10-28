"""Source test kit: the Simulator's plant over every protocol Historian reads.

Development and CI only (``pip install simcraft[testkit]``, ``simcraft testkit``): its
libraries are not in the image, so it cannot run there, and nothing in the product points to it. Each server publishes the same plant
(:mod:`.plant`), so a check can compare what Historian archived with what was published:

- :mod:`.csv_files` writes sample files in every layout Historian reads, and one with errors;
- :mod:`.piwebapi` answers as PI Web API does (Basic auth, paging, recorded, interpolated,
  digital states, 503 bursts, slow answers);
- :mod:`.mqtt` runs a broker and publishes values, flat JSON and nested JSON;
- :mod:`.modbus` serves registers in every data type and byte order Historian lists;
- :mod:`.sql` writes wide, long and naive-time tables into a PostgreSQL database.

OPC UA is the Simulator itself (``simcraft serve``).
"""
