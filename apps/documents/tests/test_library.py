"""The library without HTTP: reading each kind of file, cutting passages, finding the plant's tags,
keeping revisions and searching by words and by meaning (``doccraft.library``)."""

from __future__ import annotations

from io import BytesIO

import pytest

from doccraft.library import extract, passages, tags
from doccraft.library.embed import DIMENSIONS, HashEmbedder, embedder
from doccraft.library.indexer import index_file
from doccraft.library.search import fts_query
from tests.conftest import FILES, GUIDE, docx_bytes

INCIDENT = (FILES / "incident.pdf").read_bytes()
IDS = tags.index(["PIC-1002", "LIC-1004", "FIC-1201", "LV-1004", "FIC-1001", "TIC-1209", "U-200"])


def test_a_pdf_keeps_its_pages_title_and_headings():
    read = extract.extract(INCIDENT, "INC-2026-007.pdf")
    assert read.format == "pdf" and read.pages == 2
    assert read.title.startswith("Incident report INC-2026-007")
    headings = {section.heading[-1] for section in read.sections if section.heading}
    assert {"Summary", "Causes", "Actions", "Lessons"} <= headings
    causes = next(s for s in read.sections if s.heading and s.heading[-1] == "Causes")
    assert causes.page == 1 and "1.6 to 2.4" in causes.text


def test_word_excel_markdown_and_csv_are_read_with_their_structure():
    word = extract.extract(docx_bytes("Start-up", "Open FV-1003 slowly."), "a.docx")
    assert word.sections[0].heading == ["Start-up"] and "FV-1003" in word.sections[0].text

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Instruments"
    sheet.append(["Tag", "Range", "Calibration"])
    sheet.append(["TT-1209", "0-400 C", "12 months"])
    out = BytesIO()
    book.save(out)
    excel = extract.extract(out.getvalue(), "datasheet.xlsx")
    assert excel.sections[0].heading == ["Instruments"]
    assert (
        "Tag: TT-1209" in excel.sections[0].text
        and "Calibration: 12 months" in excel.sections[0].text
    )

    markdown = extract.extract(GUIDE.encode(), "guide.md")
    assert [s.heading[-1] for s in markdown.sections if s.heading][-2:] == [
        "4.1 Valve stiction",
        "4.2 Sensor drift",
    ]
    table = extract.extract(b"tag;range\nFT-1001;0-80\n", "list.csv")
    assert "FT-1001" in table.sections[0].text


@pytest.mark.parametrize(
    ("data", "name", "reason"),
    [
        (b"%PDF-1.7 broken", "x.pdf", "read"),
        (b"PK\x03\x04 not a zip", "x.docx", "read"),
        (b"\x00\x01", "x.exe", "kind"),
    ],
)
def test_a_file_that_cannot_be_read_says_why(data, name, reason):
    if extract.format_of(name) is None:
        assert reason == "kind"
        return
    with pytest.raises(extract.Unreadable):
        extract.extract(data, name)


def test_passages_overlap_but_never_cross_a_heading():
    words = " ".join(f"w{i}" for i in range(800))
    cut = passages.cut(
        [
            extract.Section(words, 3, ["Long"]),
            extract.Section("Short section about FIC-1001 " * 10, 4, ["Other"]),
        ],
        words=350,
        overlap=50,
    )
    long = [p for p in cut if p.section == "Long"]
    assert len(long) == 3 and long[0].text.split()[-50:] == long[1].text.split()[:50]
    assert all(p.page_from == 3 for p in long)
    assert cut[-1].section == "Other" and cut[-1].page_from == 4
    assert [p.seq for p in cut] == list(range(len(cut)))


def test_only_tags_the_plant_knows_become_links():
    text = "PIC-1002 swings; see page 12, ISO 9001, PIC 1002 again, LV1004 at 100 %, XY-9999."
    assert tags.known(text, IDS) == ["LV-1004", "PIC-1002"]
    assert tags.normal("pic 1002") == "PIC-1002"
    assert "U-200" in IDS and "plant" not in tags.index(["plant", "Simulated unit"])


def test_indexing_embeds_each_passage_and_links_its_assets():
    done = index_file(INCIDENT, "INC-2026-007.pdf", IDS, HashEmbedder())
    assert done.pages == 2 and done.passages
    assert done.vectors.shape == (len(done.passages), DIMENSIONS)
    linked = {asset for found in done.assets for asset in found}
    assert {"PIC-1002", "LIC-1004", "LV-1004", "FIC-1201"} <= linked
    assert (
        sum("PIC-1002" in found for found in done.assets) >= 3
    )  # the title's tag is in every heading


def test_without_a_model_file_the_hashed_stand_in_searches_by_words():
    assert embedder("").name == "hash-384" and embedder("/nowhere").name == "hash-384"
    hashed = HashEmbedder()
    near = (
        hashed.query("valve stiction dead band")
        @ hashed.passages(["the valve stiction and its dead band"])[0]
    )
    far = (
        hashed.query("valve stiction dead band")
        @ hashed.passages(["boiler feed water chemistry"])[0]
    )
    assert near > far


def test_the_keyword_query_quotes_words_and_drops_stopwords():
    assert fts_query("why does FIC-1003 oscillate?") == '"FIC 1003" OR "fic" OR "oscillate"'
    assert fts_query("the of and") == '""'
    # Quotes and FTS5 operators in a question are words, never syntax.
    assert fts_query('valve" OR NEAR(x') == '"valve" OR "near"'


def test_a_bad_folder_id_in_the_query_is_refused_not_a_crash(client):
    # API fuzzing, 2026-10-31 (D17): this answered 500.
    answer = client.post(
        "/api/documents",
        params={"filename": "a.txt", "folder": "woo\x80", "issued": "k\x19a"},
        content=b"hello",
    )
    assert answer.status_code == 422, answer.text


def test_a_file_that_takes_too_long_to_read_is_stopped():
    # Security test 2026-10-31 (D10): reading runs in a worker with a time limit; when the
    # worker stops it, the person reads why.
    import pytest
    from plantcraft_sdk import sandbox

    from doccraft.library import extract

    class Stopped:
        timeout = 1.0
        crashes = 0

        def run(self, fn, payload):
            raise sandbox.CodeError("The code did not finish in 1 s and was stopped.")

        def shutdown(self):
            return None

    sandbox.use_pool(extract.EXTRACT, Stopped())
    try:
        with pytest.raises(extract.Unreadable, match="within the limits"):
            extract.extract_isolated(b"x", "slow.txt")
    finally:
        sandbox.use_pool(extract.EXTRACT, None)


def test_a_file_is_read_in_a_worker_process():
    from doccraft.library import extract

    found = extract.extract_isolated(b"Pump P-101 trips on low flow.", "note.txt")
    assert "P-101" in found.sections[0].text


def test_a_drawing_is_read_in_the_worker_process_too():
    from doccraft.library import extract
    from doccraft.plantmap.sample.draw import draw_all

    _, canvas, _ = draw_all()[0]
    data = canvas.svg().encode()
    extracted, diagrams = extract.read_isolated(data, "PID-U-100-01.svg")
    assert diagrams and diagrams[0]["items"]
    assert extracted.format == "drawing"


def test_meaning_search_walks_past_passages_the_person_may_not_read():
    """The best passages by meaning are checked a chunk at a time: when the whole first chunk
    is in folders the person may not see, the next chunks are read until enough are found."""

    import numpy as np

    from doccraft.library.search import CANDIDATES, Searcher

    class Store:
        asked: list[int] = []

        def allowed_among(self, ids, folders, assistant):
            self.asked.append(len(ids))
            return {i for i in ids if i >= 1500}  # only the 500 weakest are readable

    ids = np.arange(2000, dtype=np.int64)
    scores = -ids.astype(np.float32)  # passage 0 is the best by meaning
    best = Searcher(Store(), HashEmbedder())._best(ids, scores, {"f"}, False)
    assert best == list(range(1500, 1500 + CANDIDATES))
    assert len(set(best)) == len(best)

    class Everyone(Store):
        def allowed_among(self, ids, folders, assistant):
            return None

    assert Searcher(Everyone(), HashEmbedder())._best(ids, scores, None, False) == list(
        range(CANDIDATES)
    )


def test_a_document_that_looks_confidential_is_kept_from_the_assistant(client, runtime):
    """Security test D11 (2026-10-31): a "not for the assistant" line inside the text was only
    text, and answers quoted the PIN it held. Its first revision now switches the assistant
    off; a plain document keeps it on, and the editor can switch it back on."""

    from tests.conftest import index, send

    secret = send(
        client,
        "CONF-001.md",
        b"# Access\n\nNot for the assistant.\n\nThe panel PIN is 4821 and the VPN password: "
        b"Valve-2026.\n",
    )
    plain = send(client, "SOP-001.md", b"# Start-up\n\nOpen the suction valve, then start P-101.\n")
    assert index(runtime) == 2
    assert runtime.library.store.document(secret["doc_id"])["assistant"] is False
    assert runtime.library.store.document(plain["doc_id"])["assistant"] is True

    from doccraft.library.indexer import looks_confidential

    assert not looks_confidential(["Enter the password to unlock the keypad."])
    assert not looks_confidential(["The PIN is required at start-up."])
    assert looks_confidential(["API key = sk-test-123456"])
    assert looks_confidential(["Documento confidencial."])


def test_links_to_assets_wait_in_a_queue_editors_clear_in_a_batch(client, runtime, fake):
    """D5: the assets found in a document's text wait for a person below the threshold, are
    approved or rejected several at once, and a rejected one is not suggested again."""

    from tests.conftest import client_for, guide, index

    doc = guide(client, runtime)
    queue = client.get("/api/asset-links").json()
    assert queue["threshold"] == 0
    mine = [link for link in queue["links"] if link["doc_id"] == doc["doc_id"]]
    assert len(mine) >= 2, queue
    keep, drop = mine[0], mine[1]
    ref = lambda link: {"doc_id": link["doc_id"], "asset_id": link["asset_id"]}  # noqa: E731
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get("/api/asset-links").status_code == 403
    assert client.post(
        "/api/asset-links/review", json={"links": [ref(keep)], "verdict": "approved"}
    ).json() == {"changed": 1}
    assert client.post(
        "/api/asset-links/review", json={"links": [ref(drop)], "verdict": "rejected"}
    ).json() == {"changed": 1}
    assets = {
        a["asset_id"]: a["source"]
        for a in client.get(f"/api/documents/{doc['doc_id']}").json()["assets"]
    }
    assert assets[keep["asset_id"]] == "manual" and drop["asset_id"] not in assets
    # Read again: the rejected link is not suggested again, the approved one stays.
    assert client.post(f"/api/documents/{doc['doc_id']}/reindex").status_code == 202
    index(runtime)
    left = {(l["doc_id"], l["asset_id"]) for l in client.get("/api/asset-links").json()["links"]}
    assert (doc["doc_id"], drop["asset_id"]) not in left and (
        doc["doc_id"],
        keep["asset_id"],
    ) not in left
    # Above the threshold a link is taken at once and never waits.
    runtime.store.auto_mentions = 1
    from tests.conftest import GUIDE, send

    other = send(client, "guide-2.md", GUIDE.encode(), number="DOC-TG-002")
    index(runtime)
    assert not [
        l for l in client.get("/api/asset-links").json()["links"] if l["doc_id"] == other["doc_id"]
    ]
    sources = {
        a["source"] for a in client.get(f"/api/documents/{other['doc_id']}").json()["assets"]
    }
    assert sources == {"auto"}
