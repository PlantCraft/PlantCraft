# Loop interaction

## What it detects

Whether the loop moves together with a second signal (another loop's PV, a feed or a utility
header): the largest absolute correlation between the two over a range of lags, with the lag
where it happens. A strong correlation is a lead for a shared disturbance or an interaction.

## Reference

- Bauer, Horch, Xie, Jelali and Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control.
- Thornhill and Hägglund (1997), Detection and diagnosis of oscillation in control loops: a
  plant-wide oscillation shows in several loops at once.

## Parameters

- `max_lag_samples` (default 60): the largest shift, in grid samples, tried in each direction.
- `correlation_threshold` (default 0.5): the absolute correlation that scores 100; the score is the
  best correlation divided by it.

## How to read the finding

"Correlation of 0.82 with the secondary signal, with a lag of 4 min." The sign says whether they
move together or opposite; the lag says which one leads. Check the process topology before
blaming one loop: correlation does not prove causation.

## Limits

- Needs a `secondary` signal on the loop; without it the method reports not enough data.
- Common disturbances produce correlation without any interaction.
