# PlantCraft next to MES, data lake and your own LLM

For an integrator, or a plant's IT, whose site already has a MES, a data lake and a language
model of its own on its network, and who asks: where does PlantCraft fit, and what goes where?
The short answer: PlantCraft reads the plant, keeps its history and analyses, and hands them on.
It never writes to the plant or the MES, and it never sends anything out by itself.

```text
Level 4 / 3   MES, ERP          data lake                 your LLM          your agents
                 │  ▲               ▲                        ▲                  │
   SQL, CSV, MQTT│  │API v1    files│(the lake pulls)  OpenAI│API          MCP│(read-only)
     (read-only) ▼  │               │                        │                  ▼
Level 3 / 3.5  ┌──────────────────────────────────────────────────────────────────────┐
               │ PlantCraft + Historian    data/lake-export/    assistant    MCP server │
               └──────────────────────────────────────────────────────────────────────┘
                                   ▲ read-only: OPC UA, PI Web API, Modbus
Levels 0 to 2                      DCS, PLC, plant historian
```

Where it is installed and which conduits it opens: [security-guide.md](security-guide.md).

## 1. Your own language model

PlantCraft's assistant (Desk › Assistant and the side panel of every page,
[assistant.md](assistant.md)) answers with any **OpenAI-compatible** server: vLLM, Ollama, LM
Studio, TGI, LiteLLM or the company's own gateway. Nothing is sent to any model until an
administrator adds one.

1. **Setup › Language models › Add a provider**: format *OpenAI-compatible*, the address
   (`http://llm.plant.local:11434/v1` for Ollama, `http://<host>:8000/v1` for vLLM), the model
   names, and a key only if your server asks for one.
2. **Test**: the first model that answers becomes the default. **Models by use** can give the
   assistant, the Help and each app's uses another model, or none.
3. **Firewall**: a model on the plant's network is reached over the plant conduit (Z4), so
   `firewall.sh` must list its `host:port`, as for a PI server. A model in the cloud goes only
   through `llm-egress`, which opens a tunnel to the providers' hosts and nothing else.
   `PLANTCRAFT_LLM=off` in `.env` forbids models in the whole installation.

**What the model sees.** It has no database access: it reads the plant through read-only tools,
as the person who asks, only what that person may open, and each tool call is in the audit log
(`assistant.tool`). Nothing it says is written anywhere but the chat.

**Choosing the model.** The assistant needs a model that **calls tools** (OpenAI function
calling) and a context of **16k tokens or more** (its instructions and tools take several
thousand). Checked so far:

| Model | Server | What we checked |
|---|---|---|
| `qwen2.5:1.5b` | Ollama, CPU only | Answers, calls a tool and uses what it read, and a question in Desk that reads the demo plant (`tests/test_ollama_live.py`, every Monday and on changes to the model client: `.github/workflows/ollama.yml`). Too small for good answers: it proves the path, not the quality |
| OpenAI and Anthropic models | Their APIs | The full battery ([llm-battery.md](llm-battery.md)) |

For real use, pick a model of at least 7-8B parameters with tool calling (Qwen 2.5/3, Llama 3.1+,
Mistral Small) on a GPU; a CPU answers in minutes, not seconds.

**Ollama: raise the context.** Ollama's default context is small (2,048 to 4,096 tokens,
depending on its version) and it cuts longer requests without an error: the assistant then
forgets its tools. Start it with
`OLLAMA_CONTEXT_LENGTH=16384` (or a `num_ctx` in a Modelfile).

**Check your model before people use it.** From a clone of the repository, on a machine that
reaches the server:

```bash
PLANTCRAFT_TEST_OLLAMA_URL=http://llm.plant.local:11434/v1 \
PLANTCRAFT_TEST_OLLAMA_MODEL=qwen2.5:14b PLANTCRAFT_TEST_BUDGET=off \
  pytest -v -s tests/test_ollama_live.py
```

It works with any OpenAI-compatible server, not only Ollama. The attack and quality battery runs
the same way: `python -m tests.llm_battery --model <name> --endpoint <url>` ([llm-battery.md](llm-battery.md)).

## 2. Your own agents reading PlantCraft (MCP)

An agent of the MES, or one an integrator builds, can read the plant through PlantCraft's
**read-only MCP server** ([assistant-access.md](assistant-access.md)): assets, signals, values,
history, the apps' results and events. An administrator turns it on in **Settings › AI assistant
access (MCP)**; each person creates their own token (`pcat_...`, at most 365 days) and the agent
reads as that person, audited (`mcp.tool`). For a system rather than a person, create a person
for it (a viewer with only the apps it needs) and give its token to the agent.

## 3. Plant data into the data lake

Two ways, both started from the lake's side: PlantCraft opens no connection to it.

### Files the lake picks up (Historian › Exports)

1. In **Historian › Exports**, put the tags in the list and **Save** the export.
2. An administrator sets **Send to the data lake** to *Every hour* or *Every day*.
3. The Historian's collector writes each period that ended (UTC hours or days, five minutes
   after they end) into the install folder's `data/lake-export/`:

```text
data/lake-export/
  unit-100-to-the-lake-3f9c1a2b7d4e/
    signals.csv                                 tag, name, unit, kind, range
    date=2026-11-03/
      unit-100-to-the-lake-3f9c1a2b7d4e_20261103T1400Z.csv
```

Each CSV is long: `time` (UTC, ISO 8601), `signal`, `tag`, `value`, `unit`, one row per value,
as recorded or, if the export has a resolution, one mean (or first, last, min, max) per step. The
`date=` folders are partitions that Spark, Databricks, Fabric, Synapse, Athena and DuckDB read as
they are. A file appears whole (it is written aside and renamed); a period written again replaces
its file under the same name. After a stop, the feed catches up from where it left off.

How the lake takes them: share the folder (SMB or NFS) to its ingestion, point its agent at it
(Azure Data Factory's self-hosted runtime, the Fabric on-premises gateway, NiFi, Logstash), or
copy it on a schedule (`rsync`, `robocopy`). Files older than 7 days are deleted from
`data/lake-export/` (`HISTCRAFT_LAKE_KEEP_DAYS`, 0 keeps them), so a lake that stops reading never
fills the server. The backups leave the folder out: the lake keeps the copies.

Only the tags in the list are sent, not the asset tree: export the tree once from PlantCraft
(assets › export, JSON, CSV, B2MML or AF XML, [your-data.md](your-data.md)) and join on the tag.

### Reading API v1

For a lake that pulls by itself (a notebook, a pipeline), API v1 answers with JSON over HTTPS:
`GET /api/v1/signals/{id}/series?start&end&step` for history, `/api/v1/assets` for the tree,
`/api/v1/results` and `/api/v1/events` for what the apps found ([api-v1.md](api-v1.md)). Use the
token of a person made for the lake (section 2): reads are limited to what that person may open,
and audited.

## 4. MES data into PlantCraft

The Historian reads (never writes) SQL tables through its gateway (one checked `SELECT` per
source), CSV files dropped in `data/histcraft-csv/`, MQTT and Modbus TCP, besides OPC UA and PI Web
API: a MES's production orders, lab results or batch states become signals beside the process
values. Nothing goes back to the MES.

## 5. For IT, in one list

- **Read-only toward the plant and the MES.** No write path to a DCS, PLC, PI, OPC UA server or
  MES database; the tests hold it (`tests/test_read_only.py` in the Historian).
- **Nothing out by default.** No telemetry, update check or CDN. The only outbound connections
  are the sources the administrator adds and, if switched on, the model they approve.
- **The lake pulls.** Files in a folder, or API v1 with an audited token: PlantCraft holds no
  credential of the lake.
- **Only administrators** turn a data lake feed on, change one or delete one: a feed runs with no
  person behind it. Each change is in PlantCraft's audit log (`histcraft.export.lake`).
- **Tokens end.** MCP and API tokens last at most 365 days, and revoking one, or turning off a
  person, stops it at once.

## What is not there yet

- Parquet files, and writing straight into S3, ADLS or a lakehouse (by design PlantCraft opens no
  connection out; a lake agent or a copy job does that step).
- Apps' results and events in the lake files: read them from API v1 for now.
- An event or order pushed from the MES into PlantCraft: today the Historian reads it (SQL, CSV,
  MQTT).
