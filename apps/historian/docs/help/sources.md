# Sources

A source is one plant system Historian reads: an OPC UA server, a PI Web API, CSV files, or,
through the gateway, an MQTT broker, a Modbus TCP device or an SQL database, or the edge nodes
of a Sparkplug B broker.
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
  shaded on the signal's trend; bad values are gaps. With OPC UA the status code is kept too
  (like `UncertainLastUsableValue` or `BadSensorFailure`), and so are the limit bits (a value
  pinned at its low or high limit, or constant), so a good value that hits its high limit is
  archived where it did. CSV files report a quality only in a
  `quality` column (long layout); apps' series report none: their values count as good.
- **Mode**: where the history of its signals comes from (read from the source, archived here,
  or both), unless a signal sets its own.
- **Settings of this source's signals**: retention, scan, deviation (% of span) and max
  interval for every signal of the source. Empty fields take the general settings; a signal's
  own value wins over the source's (see Settings).
- **Integration**: who answers for the source and how often it must deliver. **Owners** are
  people or groups of PlantCraft (`user:ana, group:automation`); **Contact** says how to reach
  the team that runs the connection; **Expected interval** is how often a new value must arrive
  on at least one of its signals (empty: not watched). When the source disconnects, or sends
  nothing for longer than expected (*Source late*), PlantCraft tells the owners in Messages and
  by email, with the contact, and settles the message when the source is back. The source's
  page lists its owners and the **history** of its states (connected, disconnected), kept 90
  days.
- **Test** asks the collector to connect once and report the server's answer.
- **CSV files**: a file, or a pattern in the last part of the path (`/csv/lab/*.csv`), that
  another application keeps writing. The collector checks it every **Check every (minutes)**
  (default 5), archives the lines after the last archived value and new files, and never moves
  or changes them. Its signals exist only in the archive. The layouts and time rules are those
  of Imports; a file loaded once belongs in **Imports**. Files read the way you checked them
  (columns, time format), with every tag becoming a signal, are an import that **repeats from
  a folder**: it is listed here too, marked **Repeats**.
- An app merged into another (Twin, CPMCraft and DataCraft into Analytics) shows "App retired":
  nothing writes its series any more, and an admin may remove it with its signals.
- **Subscribe to changes** (OPC UA, off by default): the server reports each change, sampled
  at the signal's scan period, instead of Historian reading every scan. A value that holds is
  taken again every scan period, so compression works as with a scan. A node the server will
  not monitor is read every scan instead. Historian only monitors values; it changes nothing on
  the server.
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
  Store and forward: values the gateway reads while the collector is away wait in its disk buffer and arrive in
  order when the collector is back, also after a gateway restart; a batch sent twice is taken
  once. The suite's health raises a warning when more than 64 MB waits.
- **Sparkplug B** is read by the collector, which subscribes to the broker (`tcp://` or
  `ssl://`) as a host that only listens: births, data and deaths of one group, or of all when
  the group is empty. It never publishes, so it is not a primary host and never asks a node to
  be born again. With *Add signals from births* on, each metric a birth describes becomes a
  signal by itself (tag `<group>.<node>.<device>.<metric>`, with its kind and unit); otherwise
  **Browse** lists them to add. A death marks the node's or device's values bad. A node born
  before Historian connected sends data by alias that no birth named: its state counts them,
  and they are read from the node's next birth (restart it to have them now).
- **Laboratory results (LIMS)**: an SQL source marked so writes each row as a laboratory result
  at its sampling time, with its status (uncertain until approved, bad when rejected) and the
  times it reached the laboratory and was approved. A row read again unchanged is not rewritten.
