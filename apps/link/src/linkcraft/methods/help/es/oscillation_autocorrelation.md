# Oscilación

## Qué detecta

Una oscilación sostenida y regular del lazo: del error de control (PV − SP) cuando se conoce el
setpoint, y si no, de la PV. La oscilación es el problema de desempeño más común de los lazos
industriales, causada por una sintonía agresiva, una válvula que se traba o una perturbación
oscilante de otro lazo.

## Referencia

- Thornhill y Hägglund (1997), Detection and diagnosis of oscillation in control loops, Control
  Engineering Practice: la oscilación se manifiesta como un pico claro de la función de
  autocorrelación (ACF) después del desfase cero.
- Thornhill, Huang y Zhang (2003), Detection of multiple oscillations in control loops, Journal of
  Process Control 13(1): la regularidad r = período medio / (3 × desviación estándar de los
  períodos entre cruces por cero alternos de la ACF); la oscilación es regular cuando r > 1.

## Parámetros

- `min_lag_samples` (por defecto 3): el menor desfase de la ACF, en muestras de la grilla de
  análisis, buscado para el pico; fija el período más corto que se puede ver.
- `max_lag_samples` (por defecto none): el mayor desfase buscado; none usa toda la ventana.
- `min_cycles` (por defecto 3): el número de ciclos que debe contener la ventana antes de que la
  puntuación sea completa; un período demasiado largo para la ventana baja la puntuación.
- `min_autocorrelation` (por defecto 0.3): el pico de la ACF a partir del cual una repetición
  cuenta como oscilación.
- `min_regularity` (por defecto 1): la regularidad r a partir de la cual la oscilación cuenta como
  sostenida (Thornhill, Huang y Zhang usan 1).

## Cómo leer el hallazgo

"Oscilación con un período de unos 5 min, 72 ciclos en la ventana (autocorrelación 0.89,
regularidad 100)." Es un diagnóstico que se muestra como alerta, no forma parte del producto de
salud. El período ayuda a encontrar la causa: un período cercano al tiempo de respuesta propio del
lazo apunta a la sintonía o a la válvula; el mismo período en varios lazos apunta a una sola
fuente que se propaga por la planta (vea Interacción entre lazos). "Sin oscilación sostenida ...
el período es irregular" significa una perturbación puntual o un escalón de setpoint, no un ciclo.

## Límites

- Una detección preliminar: no distingue una oscilación causada por la sintonía de una causada por
  una perturbación externa (brecha G29) o por fricción estática (vea Detección de fricción
  estática).
- No se pueden ver períodos más cortos que unas tres muestras de la grilla (3 min en la grilla por
  defecto de 60 s).
- Una oscilación cuyo período deriva mucho en la ventana no es regular y no se señala.
