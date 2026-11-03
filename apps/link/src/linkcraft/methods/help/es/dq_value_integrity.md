# Integridad de los valores

## Qué detecta

Si se puede confiar en los valores de la PV: la fracción de muestras inválidas (texto, infinito,
vacío, fuera de los límites físicos cuando están fijados) y el tramo más largo durante el cual la
PV se mantuvo exactamente constante (un transmisor congelado). Forma parte de la compuerta de
calidad de datos.

## Referencia

- Heurística de ingeniería: un valor de proceso real nunca se queda exactamente constante por
  mucho tiempo; una medición congelada o inválida se descarta antes de juzgar el lazo, como en
  todas las herramientas de CPM que cubre el estudio (Bauer et al. 2016).

## Parámetros

- `frozen_fraction_limit` (por defecto 0.5): la mayor fracción de la ventana en que la PV puede
  quedarse en un valor antes de que los datos se rechacen como congelados.
- `invalid_fraction_limit` (por defecto 0.2): la mayor fracción de muestras inválidas antes de que
  los datos se rechacen.
- `lower_limit` (por defecto none): el límite físico inferior de la PV; los valores por debajo de
  él son inválidos.
- `upper_limit` (por defecto none): el límite físico superior de la PV; los valores por encima de
  él son inválidos.

## Cómo leer el hallazgo

"Los valores de la PV son sólidos." o "PV trabada en el mismo valor durante 100% de la ventana."
Una ventana rechazada da el estado "Datos no utilizables" y los métodos de CPM no se ejecutan:
revise el transmisor, su comunicación y la señal en PlantCraft.

## Límites

- Las señales calculadas o de baja resolución, y los analizadores que mantienen su último valor,
  pueden parecer congelados sin estarlo.
- Sin límites, los valores físicamente imposibles no se detectan.
