# Recorrido de la válvula

## Qué detecta

Cuánto trabaja la válvula: el movimiento acumulado de la salida por hora (recorrido) y el número
de cambios de dirección por hora (inversiones). El exceso de recorrido e inversiones desgasta la
empaquetadura y los actuadores y a menudo viene del ruido o de una sintonía agresiva.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. El recorrido y las
  inversiones de la válvula son indicadores estándar de salud de válvulas; los umbrales son
  heurísticas de ingeniería.

## Parámetros

- `max_travel_per_hour` (por defecto 200): el recorrido acumulado de la salida, en % por hora, que
  puntúa 100. A los lazos rápidos (flujo) se les permite más y a los lentos o de promediado menos,
  según su tipo de lazo.
- `max_reversals_per_hour` (por defecto 60): el número de cambios de dirección por hora que puntúa
  100.
- `reversal_epsilon` (por defecto 0.05): el menor movimiento de la salida, en %, contado al buscar
  un cambio de dirección.

## Cómo leer el hallazgo

"La salida recorrió 320% por hora, con 45 inversiones por hora." La puntuación es la peor de las
dos tasas. Un recorrido alto con una PV ruidosa apunta a ruido que llega a la válvula (filtro,
derivativa); un recorrido alto con una oscilación, a la sintonía o a la fricción estática.

## Límites

- La salida es el comando del controlador, no la posición del vástago.
- Contado sobre la grilla de análisis: el promediado en cada paso de la grilla oculta el
  movimiento rápido, y se puede contar como máximo una inversión por muestra de la grilla.
