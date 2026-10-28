# Sources

A source is one plant system Historian reads: an OPC UA server, a PI Web API, CSV files, or,
through the gateway, an MQTT broker, a Modbus TCP device or an SQL database.
Calculated signals (see Signals) have a source of their own, `calc`, created with the first one.
Apps' derived signals have a source of their own, which only the app writes. Only admins add,
change or remove sources.

- **Endpoint**: `opc.tcp://host:port/path`, the PI Web API base URL, or the CSV file or pattern
  (`/csv/lab/*.csv`).
  Historian only reads: OPC UA Read, Browse and HistoryRead, PI Web API GET. It never writes
  to a plant system.
- **Sign-in**: anonymous, or a user name with a password. A typed password is stored
  encrypted and never shown again; it can also come from a `HISTCRAFT_SECRET_*` environment
  variable.
- **Security** (OPC UA): None, Sign, or Sign and encrypt, with the policy the server offers
  (Basic256Sha256, Aes128_Sha256_RsaOaep or Aes256_Sha256_RsaPss). Download Historian's
  certificate from the form and add it to the server's trusted list. The first **Test** shows
  the server's certificate (its SHA-256, subject and dates): compare it with what the server's
  administrator sees, then **Trust** it. From then on a server presenting another certificate
  is refused.
- **Quality**: OPC UA and PI tell the quality of each value. Uncertain values are archived and
  shaded on the signal's trend; bad values are gaps. CSV files report a quality only in a
  `quality` column (long layout); apps' series report none: their values count as good.
- **Mode**: where the history of its signals comes from (read from the source, archived here,
  or both), unless a signal sets its own.
- **Settings of this source's signals**: retention, scan, deviation (% of span) and max
  interval for every signal of the source. Empty fields take the general settings; a signal's
  own value wins over the source's (see Settings).
- **Test** asks the collector to connect once and report the server's answer.
- **CSV files**: a file, or a pattern in the last part of the path (`/csv/lab/*.csv`), that
  another application keeps writing. The collector checks it every **Check every (minutes)**
  (default 5), archives the lines after the last archived value and new files, and never moves
  or changes them. Its signals exist only in the archive. The layouts and time rules are those
  of Imports; a file loaded once belongs in **Imports**. Files read the way you checked them
  (columns, time format), with every tag becoming a signal, are an import that **repeats from
  a folder**: it is listed here too, marked **Repeats**.
- An app merged into another (Twin, CPMCraft and DataCraft into Link) shows "App retired":
  nothing writes its series any more, and an admin may remove it with its signals.
- **Browse** lists the server's variables with their units and ranges, so you can add many
  signals at once. Signals already archived are marked. Leave scan and deviation empty to use
  the source's or the general settings; a variable the server gives no range for is then
  compressed to that share of its value instead of its span.
- **MQTT, Modbus and SQL** are read by the gateway (Telegraf), which pushes every value to the
  collector; their signals exist only in the archive. MQTT: the broker, the topics (`+` one
  level, `#` the rest) and whether a message is a number or JSON. Modbus TCP: the device, its
  slave id and each register or coil to read (type, address from 0, data type, byte order,
  scale; a 64-bit value names all eight bytes, ABCDEFGH to GHEFCDAB). SQL: the database, its
  connection string with `{password}` where the password goes, and one SELECT run every scan
  period (10 s when empty) by a user that can only read. The time column and the tag columns
  are not signals of their own. Only rows newer than a signal's last value are archived.
  **Browse** lists what the gateway has sent; a source silent for 60 s shows Disconnected.
