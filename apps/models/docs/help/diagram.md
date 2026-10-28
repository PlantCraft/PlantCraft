# Drawing diagrams

The **Diagram** tab draws the selected class: each component is drawn with its library icon at
the place its `Placement` annotation gives, and each `connect` equation with its line.

Every change made on the diagram is written in the class's text, the way you would write it
yourself, and the diagram is drawn again from the text. The text stays the one source: what you
draw is what you can read, compare and keep in version control.

| To | Do |
|---|---|
| Add a component | Open **Library** on the left, find the class (search, or open the packages), and drag it onto the diagram; or drag a model or block of the **Files** tree |
| Move a component | Drag it |
| Rotate it a quarter turn | Select it and press **R** (or the rotate button) |
| Delete a component | Select it and press **Delete**; its connections go with it |
| Connect two connectors | Drag from one connector to the other (the cursor becomes a cross over a connector) |
| Delete a connection | Click its line and press **Delete** |
| Change a parameter | Select the component; its parameters are on the right. Write a value and press **Apply**; an empty value removes yours and the default applies again |
| Zoom, pan | Mouse wheel; drag the empty background |

A new component gets a name from its class (`gain`, `gain1`...). To rename it, change it in the
text, together with its connections.

Connectors only connect when they are compatible (a `RealOutput` to a `RealInput`, a fluid port
to a fluid port...). The diagram writes the `connect`; **Check** says if the two do not fit.

Inherited components (from an `extends`) are drawn but not moved: change them in the base class.

## A plant of your own components

Build the parts once, then connect them, as in OpenModelica:

1. **New class**, start from a component: a **signal block** (input `u`, output `y`), a
   **thermal component** (a heat port) or an **electrical component** (two pins). Each comes
   with its connectors, parameters, an equation to change and an icon.
2. **New class**, start from a **System**: an empty diagram with an `experiment`. An empty
   diagram says so, with a button that opens the **Library**.
3. Open the system's **Diagram** and drag your components from the **Files** tree (and
   sources, sensors or controllers from the **Library**). Connect them and **Simulate** the
   system: every component runs together.

A component changed later changes every system that uses it. A class cannot be dropped into
itself.

## The library

**Library** lists the Modelica Standard Library 4.0.0. Click a class to read its icon,
parameters, documentation and text; drag it onto a diagram to use it. Packages of documentation
and internal classes are not listed.

## Documentation

The **Documentation** tab shows the class's `Documentation(info = "<html>...</html>")`
annotation. It is shown without any script and without links out of the page.
