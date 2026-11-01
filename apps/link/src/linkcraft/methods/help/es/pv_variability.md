# Variabilidad de la PV

## Qué detecta

Cuánto se mueve la variable de proceso alrededor de su media: desviación estándar, rango y
coeficiente de variación en la ventana. Reducir la variabilidad es lo que permite a una planta
operar más cerca de sus límites.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. La varianza y la
  desviación estándar son medidas básicas de CPM; la puntuación es una heurística de ingeniería.

## Parámetros

- `variability_tolerance` (por defecto 1): la desviación estándar, en la unidad de la PV, que
  puntúa 100 (la peor); la puntuación es la desviación estándar dividida por ella.

## Cómo leer el hallazgo

"Desviación estándar de 0.42 alrededor de la media 50.1 (rango 2.3)." Compare lazos del mismo
tipo, o el mismo lazo a lo largo del tiempo; por sí solo, un número dice poco sin la tolerancia
fijada para el proceso.

## Límites

- La variabilidad por sí sola no separa un problema del controlador de una perturbación del
  proceso o de cambios de setpoint (la variabilidad incluye los movimientos de setpoint).
- La tolerancia es absoluta: fíjela por algoritmo o por lazo para las PV que no están en % del
  span.
