# Resumen

La primera página de Analytics: un tablero de widgets que solo muestra, sin botones encima. Una
ejecución se inicia en Monitores (el **Ejecutar ahora** de cada monitor), nunca aquí.

El tablero de una persona nueva responde una pregunta: qué activos y señales están mal ahora, y
dónde:

- **Resultados por estado**: todos los resultados divididos en alarma, advertencia, desconocido y
  OK. Cada parte abre los resultados correspondientes.
- **En alarma, 14 días**: cuántos estaban en alarma y en advertencia al final de cada día.
- **Mapa de salud**: un cuadrado por activo y señal, coloreado según su estado y agrupado por área.
  Cada cuadrado abre su resultado.
- **Peores resultados**: los que están en alarma o en advertencia, la salud, la calidad o la
  puntuación más baja primero.
- **Monitores**: cada monitor, cuándo se ejecuta y cómo terminó su última ejecución.
- **Cola**: lo que espera y se ejecuta ahora, y la cola de las últimas 24 horas.
- **Horas-lazo perdidas, 7 días**: por área, el tiempo en que cada lazo no estuvo controlando,
  dividido por causa: fuera del modo normal, salida en un límite, oscilando y señal mala.
- **Control efectivo**: los lazos con la puntuación más baja primero. La puntuación es la fracción
  del tiempo en modo normal, por la fracción dentro de la banda de operación, por la fracción con
  la salida fuera de sus límites.
- **Oscilaciones compartidas por varios lazos**: lazos que ciclan con períodos dentro de un 15%
  entre sí, agrupados. El lazo que hay que revisar primero en cada grupo es el que tiene fricción
  estática, y luego el que tiene el ciclo más regular.
- **Mapa de la planta**: cada lazo coloreado según el KPI que elija (salud, control efectivo, tiempo
  en modo normal, tiempo dentro de la banda, tiempo con la salida fuera de sus límites). Bueno es
  desde 90, regular desde 75, deficiente desde 50, malo por debajo. **Mapa de calor** agrupa los
  lazos por área; el treemap los dimensiona según su criticidad, así que los lazos críticos ocupan
  más espacio. Cada lazo abre su página.

Más widgets esperan en **Personalizar**: **Analytics: más cerca del límite** lista los lazos cuya
salud está cayendo y cuántos días faltan para que llegue al límite de alarma (50). El pronóstico
es una recta ajustada a los últimos 14 días, que se muestra solo cuando ajusta (R² de al menos
0.5) y el límite está a menos de un año. **Analytics: controladores multivariables** muestra cada
APC de terceros con su límite activo más costoso.

**Personalizar** agrega, mueve y quita widgets solo para usted: un monitor, un resultado, la última
ejecución y los demás que publica Analytics. Los mismos widgets pueden ir en Hoy de Desk.
