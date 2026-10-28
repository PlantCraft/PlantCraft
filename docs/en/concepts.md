# Concepts

The words PlantCraft and the apps of the suite share.

### Source

A system the plant's data comes from: an OPC UA server with historical access,
a PI Web API or a CSV file. The scenario file names one; admins add others in the
**Historian** app. Passwords are encrypted on the server.

### Signal

A tag of a source (a NodeId in OPC UA, a point in PI, a column in CSV) with a
name and an engineering unit. A signal **in use** is one the suite follows and
the apps may read.

### Asset

A folder of the plant: site, unit, area, equipment, loop, or a kind of your
own. Assets form a tree, and each one may have signals linked to it.

### Role

What a signal is for in its asset: `pv`, `sp`, `op`, `mode` and `secondary`
for a loop, or any word (`pressure`, `vibration`...) for other assets.

### Loop

An asset of kind `loop` whose signals have loop roles. PlantCraft keeps the
loop and its signals; an app such as Analytics decides how to analyse it.

### Group

People who work together: a department, area, discipline or team. Groups form
a tree; a person may be in several, and a group's coordinator leads it and sees
the actions of the groups below. An action may go to a group, and every group
has its own conversation.

### Origin

Where an asset came from: the **scenario** file, a plant **map**, or a person
(**manual**). A sync never changes or removes what a person made.

### App

A program of the suite installed beside PlantCraft (`PLANTCRAFT_APPS`).
Each person may open all apps or only some.

### Access level

Admin, editor, viewer or dashboards only: what a person may change, here and in
the apps.

### Token and app key

A token proves to an app who you are; it lasts minutes and renews itself while
PlantCraft is open. An app key lets an app work on its own; it is shown once
and can be revoked.

### Audit log

The record of who changed what, written by PlantCraft and by the apps.
