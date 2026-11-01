# Trends

**Trends** draws signals over a period on one plot or on stacked subplots that share the time
axis. Save a trend to open it again, or download what it shows as CSV.

- **Period**: the last 15 minutes to 30 days, or a fixed "from – to".
- **Interval**: how long each drawn value covers. "Automatic" picks it from the period (about
  600 values per line); "As recorded" draws every sample.
- Add signals to a plot with the search under it; up to 8 lines per plot and 6 plots.
- **Compare with**: draws up to three earlier periods over the trend's own, each line dotted
  and lighter in its line's colour and named after its period: the **previous period** (just
  before, as long as the trend's), **1 day earlier** (yesterday over today), **1 week earlier**
  or **4 weeks earlier**. Each earlier period is read at the trend's interval and moved onto its
  time axis, so the hover shows today's clock; the line's name says which period it is. States
  (text signals) are not compared. Saved with the trend.

## Each line

Click a line's name to set it on its own, apart from the other lines:

- **Interval**: the trend's (the default) or the line's own, from 1 minute to 1 day or as
  recorded. PV every minute beside SP every hour on the same plot is two lines with two
  intervals.
- **Each interval shows**: the mean (the default), the last value, the first
  value, the minimum or the maximum of each interval. The same signal can be drawn twice, for
  example its mean and its maximum. Summaries other than the mean read the samples as recorded;
  over a very long period with too many samples the line falls back to the mean and says so
  under the chart.
- **Draw as**: a line, points, or both; between samples straight, in steps (each value held
  until the next, as a controller sees it) or smooth.
- **Colour** (automatic or chosen), **dash**, **line width** and **point size**.
- **Y axis**: left, or right with its own scale, to compare signals of different ranges on the
  same plot.

The CSV has one column per line drawn, named with its summary when it is not the mean.

## The chart

- An axis names its unit only when every line on it has the same one; with two units the
  legend and the hover still give each line its own.
- **Full screen**, above the chart on the left, shows the chart alone; Esc leaves.
- **Chart**: "As the platform" follows your theme; **Light** or **Dark** fixes the chart's
  colours, the picture included, whatever the platform's theme. The choice stays in this
  browser.
- Plotly's buttons, top right of the chart, zoom, pan and download the chart as a PNG named
  after the trend.
