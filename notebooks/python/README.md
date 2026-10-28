# plantcraft-notebook

PlantCraft from a notebook: signals, series, assets and results as pandas tables, read through
API v1 with your own access. The same package runs in PlantCraft's Notebooks (in the browser) and
in Jupyter on your computer. See Help › Notebooks in PlantCraft.

```python
import plantcraft_notebook as pc

pc.signals("FIC")  # find signals
data = pc.series(["plant:FIC-101.PV"], "-7d", "now", step=60)  # a table indexed by time (UTC)
pc.assets(type="loop")  # the plant tree
```

On your computer, connect once per session:

```python
pc.connect(
    "https://plantcraft.example.local", token="pcat_..."
)  # or PLANTCRAFT_URL, PLANTCRAFT_TOKEN
```
