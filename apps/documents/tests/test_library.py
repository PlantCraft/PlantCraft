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
