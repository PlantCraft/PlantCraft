# Compression

Historian uses **swinging-door** compression (Bristol, 1990), the method of the historians of
this category.

1. Every value read is held as the *snapshot*: reads always include it, so trends reach the
   present.
2. A held value is archived only when the next value shows that a straight line from the last
   archived value can no longer pass within *deviation* of every value read in between.
3. A value is archived at least every *max interval*, even on a flat signal.
4. Step and text signals archive every change, with the value held just before it, so a rebuilt
   step is exact.
5. Bad quality or a lost connection archives a gap marker; the next good value starts a new line.

A trend rebuilt by joining archived values with straight lines is never further than the
deviation from any value read. Averages over a grid are exact time-weighted integrals of that
rebuilt trend.
