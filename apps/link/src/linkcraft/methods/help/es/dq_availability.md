# Disponibilidad de la señal

## Qué detecta

Si las señales del lazo se registraron a lo largo de la ventana: para cada señal, la cobertura
(1 − el tiempo perdido en huecos más largos que un intervalo máximo, sobre la ventana) y el mayor
hueco. Forma parte de la compuerta de calidad de datos: si la PV cubre muy poco de la ventana, los
métodos de CPM no se ejecutan.

## Referencia

- Heurística de ingeniería. Los historians con compresión registran solo cambios, así que un
  intervalo de hasta el máximo configurado todavía cuenta como datos válidos; la revisión de los
  datos antes de cualquier juicio es el primer paso que describe el estudio de CPM (Bauer et al.
  2016).

## Parámetros

- `max_gap_seconds` (por defecto 600): el intervalo más largo, en segundos, entre dos muestras
  registradas que todavía cuenta como datos; el tiempo más allá de él es un hueco. Los lazos
  lentos (temperatura, composición) reciben un intervalo más largo según su tipo de lazo.
- `min_coverage` (por defecto 0.8): la cobertura de la PV por debajo de la cual los datos no son
  utilizables y los métodos de CPM no se ejecutan.

## Cómo leer el hallazgo

"La PV cubre 97% de la ventana." Cuando dice "La PV cubre solo 40% de la ventana (mínimo 80%)", el
estado del lazo es "Datos no utilizables" y no se da ninguna puntuación de desempeño: corrija
primero la ruta de los datos (conexión de la fuente, historian, asignación de señales en
PlantCraft).

## Límites

- Verifica que existan valores, no que sean correctos (vea Integridad de los valores).
- No distingue una falla de comunicación de un equipo detenido.
