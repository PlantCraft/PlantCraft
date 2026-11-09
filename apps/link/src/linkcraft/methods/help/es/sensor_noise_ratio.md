# Ruido del sensor

## Qué detecta

Ruido en la medición, juzgado en la escala del propio lazo: el ruido de una muestra a la
siguiente, estimado con las segundas diferencias de la PV (con la desviación absoluta mediana, para
que los escalones de setpoint y los cambios de carga no cuenten), como fracción del rango de la PV
o, sin él, del tamaño del setpoint. El ruido pasa por el controlador hasta la válvula, la desgasta
y oculta lo que hace el lazo.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. La medida es una
  heurística de ingeniería.

## Parámetros

- `relative_noise_percent` (por defecto 2): el ruido, en porcentaje de la escala del lazo, que
  puntúa 100 (el peor); alerta desde un cuarto de eso.
- `noise_ratio_threshold` (por defecto 0.35): la fracción de la variación de la PV explicada por el
  ruido en la que el ruido pesa por completo. Una PV que oscila o se mueve mucho tiene la mayor
  parte de su variación fuera del ruido, y sus movimientos de muestra a muestra son su ciclo más
  que ruido: la puntuación baja.
- `noise_abs_tolerance` (por defecto ninguno): un ruido absoluto, en la unidad de la PV, que
  puntúa 100. Vacío: una fracción de la escala del lazo.
- `pv_span` (por defecto ninguno): el rango de ingeniería de la PV; vacío, la escala es la mediana
  de |SP| (o de |PV| sin setpoint).

## Cómo leer el hallazgo

"Ruido de muestra a muestra de 1,3 (2,6 % de la escala del lazo), 95% de la variación de la
medición." Un diagnóstico mostrado como alerta, fuera de la nota. Un ruido por encima de cerca del
0,5 % de la escala en un lazo ajustado merece una mirada al transmisor, sus tomas de impulso, su
filtrado y la acción derivativa; los analizadores son naturalmente más ruidosos que las
temperaturas.

## Límites

- Un proceso más rápido que el muestreo (un caudal rápido muestreado una vez por minuto) parece
  ruido.
- En una grilla gruesa el promedio oculta el ruido.
- Una PV mantenida cerca de cero deja la tolerancia relativa estrecha: dé al lazo su `pv_span` o un
  `noise_abs_tolerance` absoluto.
