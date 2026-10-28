# Process

A **process display** draws the plant as its operators know it: the equipment from the symbol
library joined by its lines, with the plant's values on it. Colours tell the state at a glance,
tanks fill with their level, pumps light up when they run and lines move while something flows.
Diagrams only read: nothing on a diagram writes to the plant.

## Pages

One process display holds the plant: each unit or area on its own page, with the tabs under
the name. In the editor, **Add page** makes one; the page's name, its place and **Remove page**
sit beside the tabs. A symbol, value or text can open another page (A click opens › Another
page), like an off-page connector.

## Watch a diagram

- **Live** shows the values now, refreshed every few seconds (the diagram's own cadence).
- **Colours**: green is normal, amber a warning, red an alarm (it blinks), grey no data. Grey also
  means a value has not changed for 15 minutes: an old number is never shown as a healthy plant.
- Point at an element to read its values, their unit and why one cannot be read. The list under
  the diagram names every value that cannot be read.
- A large drawing can name its **parts** (Edit › Process display › Parts): tabs over it,
  **Overview** for the whole drawing and one per part, zoomed in; the tab of the part in view is
  marked, and the address keeps it (`?part=`).
- A click on a value draws its trend in a window over the diagram, with the period, the interval
  and each line's look as in Trends; **Open in Trends** goes on with it there.
- A click on a piece of equipment opens its panel beside the diagram: its values on the drawing,
  its signals (each a trend away), the dashboards that show it and **Asset page**. An element
  its editor linked elsewhere opens that instead: another diagram or a dashboard.
- **Full screen** is the browser's own: the diagram alone, live, for a control room screen, with
  the trend and the asset panel opening inside it; Esc leaves.
- A vessel's level fills the vessel's own shape, with the liquid's surface drawn as a line.

## Share a diagram

Editors of a diagram's folder share it with **Share**, like a dashboard: a **public link** opens
this diagram only, read-only and without signing in, for a wall screen or a colleague without an
account.

- Copy the link when it is made: it is shown only once. It opens for 7 to 365 days (an
  administrator can make one that opens until revoked), and stops at once when you revoke it or
  delete the diagram.
- The link shows the diagram live, with its time bar to play the window back. Add `?screen=1` to
  the link for a kiosk: the diagram alone, live, filling the screen.
- Clicks on a shared diagram open nothing: its links lead to pages that need signing in.
- Administrators review every link of the installation (dashboards, reports and diagrams) in
  **Dashboards › Public links**.

## A diagram on a dashboard

A dashboard can show a saved diagram in a panel: **Edit › Add panel › Diagram**, then pick the
diagram. The panel draws it live, scaled to fit, refreshed with the dashboard; it reads the
dashboard's **Time** window (else the panel's own) and a click opens the diagram's page.

Who sees the diagram follows its folder: a viewer who may not see that folder, or a public link
to the dashboard when the diagram is in a folder kept for some people, sees "not available"
instead, and so does everyone once the diagram is deleted. Reports take no diagram panel.

To turn through several diagrams on one control room screen, put each on its own page of a
dashboard, set the dashboard's **Config** to show the next page every so often, and open it in
full screen or by its public link.

## Go back in time

The time bar reads the whole window at once, so moving through it asks the platform nothing new.

- Pick the **window** (15 minutes to 7 days) and drag the cursor: the diagram shows the values of
  that instant.
- **Play** runs the window at 1x to 600x; **Window ends** moves the window to any past moment.
- States that other apps publish (alarms, loop health) are shown live only; in playback they are
  grey.

## Draw a diagram

Editors draw diagrams: **New diagram**, or **Edit** on a diagram.

1. **Drag equipment** from the library at the left onto the canvas (or click it to drop it in the
   middle). Search finds a symbol by name or by what it is: pump, tank, valve, column.
2. **Join it**: drag from a port (the small circles on a symbol) to another symbol or one of its
   ports. The line routes itself with square bends and follows the symbols when they move.
3. **Bind it**: click a symbol and pick the **asset it draws** (P-101, TK-1). Its colour, level
   and running are bound at once from the asset's signal roles; change any of them in the panel.
   **Value** adds a number beside the selected symbol (its PV first), with its own limits.
4. **Save**. Nothing is saved before; Cancel leaves the diagram as it was.

Or start from a draft: **From assets** lays out a unit from its equipment, loops and relations
(each with its bindings), and **Draft with assistant** drafts one from what you describe (when
the language model use *diagram-draft* is on in Setup). Both replace the canvas, Undo brings it
back, and a note says what was left out. Move things where you want them, then save.

A selected symbol has a handle at each corner: drag one to resize it (Shift frees the
proportions). A selected line has a handle on each stretch that can move: drag it to move that
stretch, and the bends stay square; **Square the route again** in its panel undoes the bends.
**Versions** (the clock in the toolbar) lists the last 30 saves and brings one back onto the
canvas; save to keep it.

Keys: Ctrl+Z and Ctrl+Y undo and redo, Delete removes, Ctrl+C, Ctrl+V and Ctrl+D copy, arrows
nudge (Shift for larger steps), R turns, F flips, Esc clears the selection. Ctrl and the wheel
zoom; Alt and drag, or the middle button, pans.

A line's **kind** draws it as process piping (its colour says what runs in it: water, steam,
gas, oil...), a signal (dashed) or a utility (dotted).
