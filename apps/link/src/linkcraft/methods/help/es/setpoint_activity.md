# Actividad del SP

## Qué detecta

Con qué frecuencia se movió el setpoint más que un umbral, como cambios por hora, y el movimiento
total. Los movimientos frecuentes del setpoint por los operadores a menudo ocultan un lazo que no
mantiene su meta por sí solo.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. La puntuación es
  una heurística de ingeniería.

## Parámetros

- `change_threshold` (por defecto 0.1): el menor movimiento del setpoint, en la unidad de la PV,
  contado como cambio.
- `max_changes_per_hour` (por defecto 6): la tasa de cambios por hora que puntúa 100; la
  puntuación es la tasa dividida por ella. Los lazos lentos (temperatura, composición) reciben una
  tasa menor según su tipo de lazo.

## Cómo leer el hallazgo

"14 cambios de setpoint (0.6 por hora)." Una tasa alta en un lazo cuyo setpoint lo fijan personas
indica que lo corrigen continuamente; en el secundario de una cascada o en un lazo manejado por
APC es lo esperado.

## Límites

- Las recetas, las transiciones y el APC mueven los setpoints a propósito.
- El setpoint del secundario de una cascada lo escribe su primario en cada muestra: cada muestra
  cuenta como un cambio.
