# Signals

Every signal PlantCraft knows, with its latest result from the Signal quality algorithm. Filter
by status, by source, by a check that flagged it, or search by id and name. Open a signal to see
why it got its result.

- **Good** (shown in PlantCraft as *OK*): every check passed.
- **Suspect** (*Warning*): at least one check warned; the data is still usable.
- **Bad** (*Alarm*): at least one check failed; loops and other apps should not trust this data.
- **Unknown**: no check could judge the signal (too few samples, unreadable, text only).

Quality is 100 minus the worst check's score: 100 is perfect, below 25 is unusable.

Signals come from PlantCraft's catalog through API v1; Analytics never keeps its own tag list.
Derived signals (series an app computed, such as Analytics' own quality and health scores) are
not checked. A signal that disappears from PlantCraft is marked missing and kept, so its history
stays.
