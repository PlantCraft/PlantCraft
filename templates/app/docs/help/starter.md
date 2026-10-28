# StarterCraft

StarterCraft keeps a note on any asset of the plant: a reading taken in the field, a reminder for
the next shift, what was changed on a loop and why.

## Notes

**Notes** lists every note, newest first, with its asset. Type in the filter to narrow the list,
or press Ctrl+K anywhere in the suite and type a word of the note.

- **New note**: pick the asset from PlantCraft's asset tree and write the text (up to 4,000
  characters). Editors and admins can write notes; viewers read them.
- **Change or delete** a note from its row. Every change is recorded in PlantCraft's audit log,
  with who made it and when.

A note names its asset; it does not copy it. When the asset is renamed in PlantCraft, the note
shows the new name. When the asset is removed, the note stays and shows the asset's id.

## Make your own app

StarterCraft is the template of the suite's apps: copy it, give it a name (`make rename
NAME=Logbook`) and follow the prompts in its `prompts/` folder.
