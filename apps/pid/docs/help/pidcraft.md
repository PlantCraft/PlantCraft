# PlantCraft PID

PlantCraft PID reads the plant's P&IDs into one plant map: the units, the equipment, the lines
between them and the control loops. Everyone with access to PID sees every drawing and the map.


## Drawings and diagrams

**Drawings** holds the plant's P&IDs. Send a file (or several) and give each one its number,
title and unit; a file sent again with the same number becomes the drawing's new revision. Each
drawing is read offline and with no language model. This
works for PDF from a CAD tool, SVG, and scans or images (PNG, JPEG, TIFF). A P&ID tool's
DEXPI export (XML) is read exactly: the tool already says what each item is and what joins
what, so nothing there is a guess. Every page that is a
diagram is listed in **Diagrams**. Each page opens with boxes over what was found and a list
of what to check first. Each finding says how sure the reader is and why.
Pick a box: if PlantCraft has that tag, the asset, its signals and what the apps say about it
are one click away.

## Plant map

**Plant map** joins all the sheets into one plant:

- the units, with the equipment in flow order and the control loops on each piece;
- the lines from one sheet to another, through the off-page connectors;
- hand valves drawn with no tag: a small circle in a gap of a line (a ball or hand valve as
  DIN/ISO 10628 tools draw it) is a valve the line runs through;
- a summary and the list **To check**.

On the map you can work with what was read:

- Pick an item to see its lines and the sheets it is drawn on. If PlantCraft already has it, its
  card opens the asset, its signals and what the suite's apps say about it.
- **Correct** or **Wrong** on any item or line, if you can edit. Wrong takes it off the map and
  out of every export. **Undo** brings it back.
- **Lists** downloads the equipment, instrument, line and loop lists as CSV.
- **DEXPI (XML)** downloads the map in the open P&ID exchange format, for tools such as AVEVA,
  Hexagon Smart P&ID or COMOS. It holds equipment, lines and instrument loops, with no drawing.
- **Asset file** goes to PlantCraft's Assets › Import, where you review it before anything
  changes.
- **Summary** downloads the map written out as a Markdown document: each unit, the equipment in
  flow order with what feeds what, the control loops, and the sheets each item is drawn on. It is
  made from the drawings with no language model; put it in PlantCraft Documents for search and the
  assistant to cite it.
- **Check against a tag list**: pick your plant's tag list (CSV or text, the tag in the first
  column) to see which tags are on both, and which are only on one. The file stays in your
  browser.

On a scan, an editor can also choose **Read again with the language model** on the diagram's
page. The page's image and what was found on it go to the model an administrator chose for
"Read a scanned diagram again" in Setup › Language models (off until then). What the model adds
is marked as the model's, with medium certainty: check it on the map.

How well it reads depends on the drawing:

- A clean vector P&ID is read almost completely.
- On a scan, the tags are read, but the lines are not.
- On a P&ID from a commercial tool, the tags are read well, but only part of the lines.

So check the lines before you use them.

## Licence

PID is a closed app: it works on an installation that holds a licence from its publisher. An
administrator adds the licence file (`.pclicense`) in PlantCraft's Apps › Licences. The licence
names the customer, this installation, the day it ends and how many drawings it covers. When it
is about to end, or has ended, a banner says so; PID keeps working 14 days after the end day, then
shows only this help and the licence's state until a new licence is added.
