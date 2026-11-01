# Algoritmo Calidad de las señales

Un algoritmo del sistema: lee cada señal habilitada en una ventana (24 horas por defecto) y ejecuta
sobre ella los métodos de Calidad de datos, con una cadencia (cada 15 minutos por defecto). Cada
ejecución es una ejecución, listada en Resultados > Historial de ejecuciones con sus conteos y su
duración, y en la página Resultados de PlantCraft.

Los administradores cambian la ventana, el monitor, qué verificaciones se ejecutan por defecto y
sus parámetros por defecto en la página del algoritmo; la configuración propia de una señal sigue
prevaleciendo.

Las ejecuciones usan la clave de app de Analytics, creada por un administrador en PlantCraft.
Después de cada ejecución Analytics publica sus resultados en PlantCraft: `linkcraft.signal_quality`
en cada señal y en cada activo (la peor de sus señales), y la serie derivada
`app-linkcraft:<signal>.quality`.

Los métodos de lazos leen estos resultados: un lazo cuya PV u OP es mala no se analiza (se informa
como bloqueado por Calidad de las señales), y una señal sospechosa se anota en el hallazgo del lazo.

## Las verificaciones

- **Disponibilidad y huecos**, **Actualidad**: la fuente envía valores, y recientemente.
- **Calidad en la fuente**: cuánto de la ventana marcó la propia fuente como malo, sustituido o
  incierto (OPC UA, PI y Canary guardan una calidad con cada valor). Un tiempo malo o sustituido
  por encima del 1% es una advertencia; por encima del 5% hace que los datos no sean utilizables;
  el tiempo incierto es como máximo una advertencia. En una fuente sin calidad no se aplica.
- **Valor congelado**, **Picos**, **Ruido**, **Resolución y compresión**, **Deriva**.
- **Fuera de rango**: valores fuera de los límites de la señal.
- **Tasa de cambio**: cambios, medidos durante al menos un minuto, más rápidos de lo que el proceso
  puede moverse. El límite es el propio de la señal (por minuto), o la mitad de su rango por minuto
  por defecto.
- **Niveles de falla del transmisor (NE 43)**: una señal de 4-20 mA leída sobre su rango como lo
  hace NAMUR NE 43. De 3.8 a 20.5 mA es medición; 3.6 mA o menos, o 21 mA o más, es el transmisor
  informando su propia falla. Cualquier nivel de falla es una advertencia y por encima del 1% de
  los valores es malo.

Fuera de rango, Tasa de cambio y NE 43 necesitan los límites de la señal (la tasa puede tener un
límite propio); sin ellos no se aplican.
