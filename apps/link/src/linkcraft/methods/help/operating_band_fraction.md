# Time in operating band

## What it detects

The share of the window in which the PV stays inside the band operations accept (for a surge
drum, between its low and high operating levels), and how much of the rest was below or above.

With limits set for the loop (`lower_limit` or `upper_limit`), it is a plain time-in-limits KPI
and applies to any loop. With the default 20–80 band it applies only to surge levels: loops whose
asset record says `level`, or loops on the surge-level algorithm, which sets
`assume_surge_level`. Elsewhere it then returns "not applicable" with the reason and stays out of
the loop's health (it does not count as a zero).

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Time inside the
  operating limits is a common industrial KPI.
- Jelali (2006), An overview of control performance assessment technology and industrial
  applications, Control Engineering Practice.
- Shinskey (1996), Process Control Systems: Application, Design and Tuning, McGraw-Hill, for the
  surge-level band. The score is the share of time inside the band.

## Parameters

- `lower_limit` (default 20): the lower limit of the operating band, in the PV's unit.
- `upper_limit` (default 80): the upper limit of the operating band, in the PV's unit; it must be
  above the lower limit.
- `margin` (default 0): a tolerance added outside both limits before a sample counts as out of
  the band.
- `assume_surge_level` (default false): run on a loop whose asset record gives no loop type; the
  Surge level algorithm sets it, because choosing that algorithm says the loop is a surge level.

## How to read the finding

"The PV was inside the 20 to 80 band 97% of the time (1% below, 2% above)." The performance is
the share inside the band and multiplies into the loop's health. Time below or above tells which
side to look at (an undersized valve, a disturbance the loop cannot reject, a band set too
tight).

## Limits

- The default 20–80 band assumes a surge level in % of span: set the limits, in the PV's unit,
  to use the block on any other loop.
- Operating limits can change with production rate or campaign.
