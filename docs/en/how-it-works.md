# How the suite works

PlantCraft sits in the middle of the suite. It holds the people, the data
connections and the plant's asset tree; each app of the suite runs beside it,
in its own container, and reads what it needs through API v1.

```flow
Plant historians | OPC UA, PI Web API or CSV, read only
PlantCraft | Sources, signals, assets, people and access
API v1 | Signed tokens, app keys and the audit log
Apps of the suite | Link and the others, each on its own
```

## What lives where

| What | Where |
|---|---|
| People, passwords, access levels and apps per person | PlantCraft |
| Data sources, the history cache and the signals in use | PlantCraft |
| Assets, their kinds and the signals linked to them | PlantCraft |
| Loops (assets of kind `loop`, signals by role) | PlantCraft |
| How each loop is analysed, rounds, scores and reports | Analytics |
| Who changed what, in PlantCraft and in the apps | PlantCraft's audit log |

## Signing in once

You sign in to PlantCraft. It gives your browser a short-lived token that
every app of the suite checks on its own, without asking PlantCraft each
time. An app that finds no token sends you to the PlantCraft sign-in and
back. Work an app does on its own (Analytics' rounds) uses an app key that an
admin issues in PlantCraft.

## Reading only

Neither PlantCraft nor the apps write to the plant: sources are read, and
whatever an app concludes is for people to check and decide.
