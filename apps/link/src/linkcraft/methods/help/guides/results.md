# Results

What every algorithm of Analytics concluded, on every asset it runs on: one row per algorithm and
asset, worst first. Each row shows the asset, its type, the algorithm and its version, the
status in the suite's words (OK, Warning, Alarm, Unknown), the result's measure (quality,
health, score), the main finding, the algorithm's labels and when it ran.

Filter by **algorithm**, **label**, **asset type**, **group** (the algorithm's responsible group)
and **status**, or search by asset, finding, algorithm or label. Each choice shows how many
results it would keep. **Clear filters** shows every result again.

**Report** prints what the filter keeps as a PDF: the counts per status and per algorithm, then
every result worst first. A filter on the label *control loop* gives the loop portfolio report;
any other filter gives the report of what it keeps.

Open a row to see the result on its own page; open the asset to see every algorithm's result on
it. Assets, loops included, are registered on PlantCraft's Assets page: Analytics reads them and
never keeps its own list. The **Run history** tab lists every run of every algorithm.
