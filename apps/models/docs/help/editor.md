# Writing Modelica code

**Code** on a model's page opens its Modelica text, and **New block library** on the Blocks page
opens a library's. The **Text** tab is a Modelica editor:

- **Highlighting** of keywords, types, numbers, strings and comments.
- **Completion**: start typing a class name (`Modelica.Blocks.`) and press **Ctrl+Space** for
  the classes of the Modelica Standard Library and of the model's package.
- **Messages on the lines**: after **Check**, every error and warning OpenModelica reports is
  marked on its line; hover it to read it. The **Messages** panel under the editor lists them
  all; click one to go to its line.
- **Ctrl+S** (or **Save**) saves the file. A file is also saved before a check, a simulation, an
  export or a diagram, so they always use what you see. If someone else saved the same file
  meanwhile, the save is refused rather than overwriting their work: copy your change, reload
  and apply it again.
- **Ctrl+F** searches, **Ctrl+Z** undoes.

## Files and classes

A model's package holds Modelica files the way every Modelica tool keeps them:

- `Name.mo` holds one top-level class (a model, a block, a package...).
- A package can be a folder: `Name/package.mo` declares the package, `Name/Model.mo` holds each
  class in it (starting with `within Name;`), and `Name/package.order` lists the classes in the
  order they are shown.

The tree on the left lists the files and, under each, the classes it declares. The green ▷ beside a
class that can be simulated (a model or block that is not `partial`) opens its simulation.
**New class** adds a class in its own file and asks what OpenModelica's "New Modelica Class" asks:
the name, the specialization (model, block, connector, record, function, package, type, class), a
description, a base class to extend, the package to put it in (a package with its own folder; the
class is added to its `package.order`) and whether it is partial. A model or block can also start
from a template (below and in Diagrams).

Limits: 200 files and 8 MB of text per package, 1 MB per file.

## Earlier versions

Every save keeps the previous version of the file; the last 50 are kept per file.

## What a model cannot use

Models runs OpenModelica on the server, so a model may not run code of its own there:

- `external` functions (C or Fortran code) are refused, unless the administrator allows them;
- `Modelica.Utilities.System`, `Modelica.Utilities.Files` and `Modelica.Utilities.Internal`
  (commands, files and the environment of the server) are refused, however they are named.

A check that meets one of these says which line it is on, and nothing is run.
