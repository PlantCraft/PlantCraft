# Historial de ejecuciones

**Resultados > Historial de ejecuciones** lista cada ejecución de cada algoritmo en una sola lista,
la más reciente primero: ejecuciones del algoritmo Calidad de las señales sobre las señales, rondas
de monitoreo y ejecuciones de algoritmos que una persona o un monitor inició sobre lazos elegidos.
No hay una página separada para señales y para lazos: los filtros **Algoritmo** y **Estado**
acotan la lista, y cada columna se puede ordenar.

Cada ejecución muestra cuándo empezó, el algoritmo, sobre qué se ejecutó, su estado, qué encontró,
cuánto tardó y qué la inició. Abra una ejecución para ver sus resultados y pregúntele al asistente
sobre ella.

Las ejecuciones también se informan a PlantCraft, que las lista en su página Resultados con las
ejecuciones de las otras apps.

## Monitores

**Monitores** indica cuándo se ejecuta cada algoritmo. La página de un monitor tiene cuatro partes:

- **Qué ejecuta**: el algoritmo, los activos o lazos sobre los que se ejecuta y cuántos datos lee
  cada ejecución.
- **Cuándo**: una vez, o cada N minutos, horas, días, semanas o meses. Cada N minutos u horas puede
  ejecutarse solo algunos días de la semana y solo entre dos horas del día (cada 15 minutos, de
  lunes a viernes, de 06:00 a 18:00); los días, semanas y meses se ejecutan a una o más horas del
  día; los meses se ejecutan en un día del mes (o en su último día) o en un día de la semana como
  el primer lunes. Un primer y un último día son opcionales. Las horas siguen la zona horaria
  elegida, primero la hora local de la instalación o UTC, así que las 06:00 siguen siendo las 06:00
  a través de los cambios de horario de verano.
- **Si falla**: cuando una ejecución no puede leer la planta o no encuentra datos, lo intenta de
  nuevo (dos veces, con cinco minutos de diferencia, por defecto) y desiste cuando la próxima
  ocurrencia del monitor llega antes. Un error en el propio algoritmo no se reintenta.
- **Responsable y prioridad**: quién responde por él (Alarms le avisa), su lugar en la cola, cómo
  se reparten sus ejecuciones y si está activo.

La vista previa de la derecha describe el monitor en palabras y lista sus próximas cinco
ocurrencias. Un monitor guardado muestra su registro arriba: cuántas ejecuciones se ejecutaron,
fallaron y se reintentaron, cuánto tardaron y desde cuándo se mantiene el último resultado.
