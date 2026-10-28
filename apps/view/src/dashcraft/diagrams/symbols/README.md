# Diagram symbols

The process symbols View's diagrams draw: one JSON file per symbol, `<category>/<id>.json`.
They are the suite's own drawings, made after the public conventions of ISO 10628-2 (equipment)
and ISA-5.1 (instruments) in the ISA-101 high-performance style: grey at rest, colour only for
what needs attention. No drawing is copied from a vendor or another tool.

## A symbol

| Field | What it is |
| --- | --- |
| `id` | Dotted id, `<family>.<kind>` in snake case (`pump.centrifugal`, `exchanger.shell_tube`); never changes once shipped. |
| `title`, `category`, `description` | What people see in the palette. |
| `w`, `h` | The viewBox, in drawing units; multiples of 10. The app draws the symbol at this ratio whatever box it is given (never squashed). |
| `stretch` | `true` for a shape that may take any proportions (a unit block, an off-page connector). |
| `svg` | The drawing: only `g path rect circle ellipse line polyline polygon text`. |
| `ports` | `{id, x, y, dir: n/s/e/w, kind: process/signal/utility/mechanical, flow?: in/out}`. |
| `anchors` | `{id, x, y, align, baseline}`: where the editor puts `tag`, `value` and `alarm` by default (instruments add `function` and `loop`, the letters and the number inside the bubble). |
| `states` | What can change: `run`, `open`, `position`, `level`. |
| `keywords`, `standard` | For search and for the assistant. |

## Drawing rules

- Grid of 10 units. Ports sit on even coordinates, on the outline or at the end of a short nozzle,
  so lines snap to them.
- Outlines are `stroke-width="2"`, details `1`; the app draws with `non-scaling-stroke`.
- No colours in the file. The body has no `fill` or `stroke` (the app's CSS gives
  `var(--pc-symbol-fill)` and `currentColor`); hollow details say `fill="none"`, solid ones
  `fill="currentColor"`. No `id`, `style`, `href`, script or image.
- `class="pc-state"`: the outline that takes the state colour (ok, warning, alarm, unknown).
  On a symbol with a level it is the outline drawn over the liquid.
- `class="pc-run"`: the part that fills when the machine runs or the valve is open.
- `class="pc-level"`: one rectangle over the straight part of the vessel, at full height; the app
  fills it from the bottom.

Adding a symbol: draw it on the grid at the size of its neighbours (a pump is 80 x 80, a manual
valve 80 x 40, an instrument bubble 60 x 60), name its ports by what flows through them
(`suction`, `discharge`, `tube_in`, `shell_out`), and check it in the gallery in light and dark.
