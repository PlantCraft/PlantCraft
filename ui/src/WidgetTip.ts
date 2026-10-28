/**
 * The hover note of a widget's marks (owner, 2026-10-27: "I pass over the squares and cannot see
 * what they are"): a square of a map, a column, a bar, a part of a split, a point of a trend says
 * what it is, where it belongs and its value, at once and in the suite's style (a browser's
 * `title` waits a second and is easy to miss).
 *
 * One note for the page, kept on `document.body` and placed `fixed` beside the pointer: a card
 * clips what overflows it, and a note drawn inside it would be cut at its edge. Its text is set
 * with `textContent`, never as markup, so an app's labels stay text.
 */

/** What a mark says: its name, the group it belongs to, a colour (its status), then rows of a
 * label and a value. */
export type WidgetTipContent = {
  title: string;
  group?: string | null;
  color?: string | null;
  rows?: Array<[string, string]>;
};

let node: HTMLDivElement | null = null;

function element(): HTMLDivElement | null {
  if (typeof document === "undefined") return null;
  if (!node || !node.isConnected) {
    node = document.createElement("div");
    node.className = "pc-wg-tip";
    node.setAttribute("role", "tooltip");
    node.hidden = true;
    document.body.appendChild(node);
    // A page that scrolls moves the mark from under the note.
    window.addEventListener("scroll", hideTip, true);
  }
  return node;
}

/** The note's lines, as elements (for the page and its test). */
export function fillTip(target: HTMLElement, content: WidgetTipContent): void {
  target.replaceChildren();
  const head = document.createElement("div");
  head.className = "pc-wg-tip-head";
  if (content.color) {
    const dot = document.createElement("i");
    dot.style.background = content.color;
    head.appendChild(dot);
  }
  const title = document.createElement("b");
  title.textContent = content.title;
  head.appendChild(title);
  target.appendChild(head);
  if (content.group) {
    const group = document.createElement("small");
    group.textContent = content.group;
    target.appendChild(group);
  }
  (content.rows ?? []).filter(([label, value]) => label || value).forEach(([label, value]) => {
    const row = document.createElement("div");
    // A row without a label is a line of text ("Collecting"); with one, a label and its value.
    row.className = label ? "pc-wg-tip-row" : "pc-wg-tip-row pc-wg-tip-line";
    if (label) {
      const name = document.createElement("span");
      name.textContent = label;
      row.appendChild(name);
    }
    const said = document.createElement("b");
    said.textContent = value;
    row.appendChild(said);
    target.appendChild(row);
  });
}

/** Shows the note beside a point of the screen (the pointer, or a focused mark's corner),
 * flipped to stay inside the window. */
export function showTip(content: WidgetTipContent, x: number, y: number): void {
  const tip = element();
  if (!tip) return;
  fillTip(tip, content);
  tip.hidden = false;
  const gap = 14;
  const { width, height } = tip.getBoundingClientRect();
  const right = typeof window === "undefined" ? Infinity : window.innerWidth;
  const bottom = typeof window === "undefined" ? Infinity : window.innerHeight;
  const left = x + gap + width > right ? Math.max(4, x - gap - width) : x + gap;
  const top = y + gap + height > bottom ? Math.max(4, y - gap - height) : y + gap;
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}

export function hideTip(): void {
  if (node) node.hidden = true;
}

/** Whether a row's text is cut (an ellipsis): a list row's note shows only then. */
function cut(target: Element): boolean {
  return Array.from(target.querySelectorAll("b, small, span, dt")).some((item) => item.scrollWidth > item.clientWidth + 1);
}

type Pointer = { clientX: number; clientY: number; currentTarget: Element };
type Focus = { currentTarget: Element };

/** The handlers that show a mark's note on hover and on keyboard focus. `onlyWhenCut` keeps it
 * for rows whose text already reads in full unless an ellipsis cuts it. */
export function tipProps(content: WidgetTipContent | (() => WidgetTipContent), onlyWhenCut = false) {
  const said = () => (typeof content === "function" ? content() : content);
  const at = (event: Pointer) => {
    if (onlyWhenCut && !cut(event.currentTarget)) return;
    showTip(said(), event.clientX, event.clientY);
  };
  return {
    onMouseEnter: at,
    onMouseMove: at,
    onMouseLeave: hideTip,
    onFocus: (event: Focus) => {
      if (onlyWhenCut && !cut(event.currentTarget)) return;
      const box = event.currentTarget.getBoundingClientRect();
      showTip(said(), box.left, box.bottom);
    },
    onBlur: hideTip,
  };
}
