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
- `min_amplitude_percent` (por defecto 0.5): la menor dispersión (desviación estándar) de la señal,
  en porcentaje de la escala del lazo (mediana de |SP|, si no de |PV|), que se juzga; un ciclo
  menor es demasiado pequeño para actuar y no se marca.
- `setpoint_settle_minutes` (por defecto 20): en el error de control, el camino de la PV hasta cada
  nuevo setpoint se pone en cero (hasta alcanzarlo por primera vez, como máximo estos minutos),
  para que una serie de escalones de setpoint no parezca un ciclo. 0 lo mantiene.

Una repetición marcada se nombra por su forma (el ajuste de medio ciclo de He et al. 2007): un
ciclo sostenido cercano a una senoide (sintonía, una perturbación oscilante) o perturbaciones
recurrentes que vuelven en un horario sin ser un ciclo (una carga o un consumidor que cambia cada
pocas horas).

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
