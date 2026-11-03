# Calidad del muestreo

## Qué detecta

Si la fuente registra el lazo con la finura y la regularidad suficientes para juzgarlo: el
intervalo mediano entre las muestras registradas de la PV (tal como las devuelve PlantCraft, antes
de la grilla de análisis), su percentil 95, el número de huecos (intervalos mucho más largos que
el mediano) y el mayor.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Los datos de
  historian demasiado gruesos o comprimidos son uno de los principales obstáculos prácticos que
  informa el estudio.
- Thornhill, Choudhury y Shah (2004), The impact of compression on data-driven process analyses,
  Journal of Process Control. La puntuación es una heurística de ingeniería.

## Parámetros

- `recommended_sample_seconds` (por defecto 30): el intervalo, en segundos, con el que se debería
  muestrear un lazo de este tipo; cada múltiplo por encima cuesta 60 puntos de puntuación.
- `gap_multiplier` (por defecto 2.5): un intervalo más largo que este múltiplo de la mediana
  cuenta como hueco; los huecos cuestan hasta 40 puntos.

## Cómo leer el hallazgo

"La PV se registró cada 10 s (mediana; recomendado hasta 30 s), con 0 huecos." El desempeño (100
menos la puntuación) se multiplica en la salud del lazo.

## Límites

- La compresión del historian (registro por cambio) alarga los intervalos de una señal estable; el
  método los toma como son, ya que esos datos realmente son más gruesos para los otros métodos.
- Cuando una ventana contiene demasiados valores registrados para una sola lectura (más de 200,000
  puntos), PlantCraft devuelve una media por paso de la grilla y el método ve ese paso. Quien llama
  sin dar muestras registradas recibe las marcas de tiempo de la grilla; el resultado dice cuál
  juzgó (`timestamp_source`).
