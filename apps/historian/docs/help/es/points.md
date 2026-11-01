# Señales

Una señal es un tag de una fuente que Historian lee o archiva. Su id de señal, `<source id>:<tag>`, es el
nombre que ven las apps.

| Configuración | Significado |
|---|---|
| Escaneo | Segundos entre dos lecturas |
| Desviación | Tolerancia de compresión en unidades de ingeniería: la tendencia reconstruida nunca se aleja más de un valor leído. 0 conserva cada cambio |
| Intervalo máximo | Un valor se archiva al menos con esta frecuencia, incluso en una señal plana |
| Retención | Días que el archivo histórico conserva sus valores |
| Escalón | Estados encendido/apagado y setpoints movidos a mano: se mantienen hasta el siguiente cambio, nunca se interpolan |
| Tipo | Número o texto |

El escaneo, la desviación, el intervalo máximo y la retención pueden quedar vacíos: la señal toma
entonces el valor de su fuente o, si no, la configuración general. Debajo de cada campo la página
muestra el valor vigente y de dónde viene ("definido en esta señal", "de la fuente", "de la
configuración general").

La instalación puede limitar cuántas señales registra Historian (`MAX_SIGNALS` en el archivo de
instalación de PlantCraft). Las señales agregadas por encima del límite se omiten, y la respuesta
indica por qué. Las series que escriben las apps no cuentan.

La página de la señal muestra su tendencia para cualquier rango y los bytes que ocupa en disco.
Eliminar una señal elimina también su archivo histórico (solo administradores).

El filtro **Tipo** de la tabla (en la columna Escaneo y desviación) muestra un tipo de señal:
leída de la planta, calculada, importada, escrita por una app o por PlantCraft.

## Notas

La página de una señal lista las notas escritas sobre ella en el período mostrado: lo que pasó y
los valores no dicen ("analizador recalibrado", "bomba B en manual de 14:00 a 15:30"). Ingeniería
agrega una en un instante o en un intervalo, y elimina las propias (los administradores,
cualquiera). Cada nota también se comunica a PlantCraft como un evento (*Nota en una señal*), así
que Events, Alarms y el asistente la ven. Los scripts y otras apps las leen y escriben con `GET` y
`POST /api/v1/annotations`.

## Valores editados

Alguien de Ingeniería puede insertar un valor donde no había ninguno, cambiar uno o eliminar uno
(una lectura tomada mientras se calibraba el sensor, un valor escrito a mano), siempre con un
motivo. El valor leído lleva entonces su marca (*insertado*, *editado* o *eliminado*), el valor
reemplazado se conserva con quién lo cambió, cuándo y por qué (la lista bajo **Valores
editados**, o `GET /api/v1/edits/{signal}`), y cada edición queda en el registro de auditoría de
PlantCraft. Las señales que escribe una app se cambian en esa app. Los scripts usan
`POST /api/v1/edits`.

## La lista de señales en una hoja de cálculo

**Exportar lista de señales**, en la página Exportaciones, escribe cada señal con su propia
configuración: `source_id`, `tag`, `address`, `name`, `description`, `unit`, `kind`, `step`,
`low`, `high`, `mode`, `scan_seconds`, `deviation`, `max_seconds`, `retention_days`, `enabled`.
Una celda de configuración vacía significa "heredar" de la fuente o de la configuración general.

**Importar lista de señales** (Ingeniería), en la página Importaciones, lee un archivo así,
separado por comas, puntos y coma o tabulaciones. Solo `source_id` y `tag` son obligatorios; las
columnas omitidas conservan lo que tienen las señales. Una fila cuya fuente y tag existen cambia
esa señal; cualquier otra fila agrega una. Historian muestra primero lo que el archivo agrega y
cambia y lista cada línea con un problema; no se importa nada hasta que todas las líneas estén
bien. Una dirección o un tipo no pueden cambiar: elimine la señal y agréguela de nuevo.

## Señales calculadas

**Agregar señal calculada** crea una señal a partir de otras con una fórmula: una conversión de
unidades, una suma de flujos, una condición, un totalizador. Su señal es `calc:<tag>` y se
archiva, se comprime y se muestra en tendencias como cualquier señal; las apps y las
exportaciones la leen de la misma manera.

- Las señales se escriben `[source:tag]`, p. ej. `[plant:FI-100.PV] * 3.6`. Una fórmula puede
  usar números, `+ - * / ** %`, comparaciones (`< <= > >= == !=`, true es 1), `and`, `or`, `not`
  y las funciones abs, min, max, sqrt, exp, log, log10, round, clip e if:
  `if([plant:XV-1.PV] > 0.5, [plant:FI-1.PV], 0)`.
- Un **totalizador** es la fórmula entera: `total([plant:FI-100.PV], per="h", reset="day")`
  integra una tasa dada por segundo, minuto, hora o día (`per` = s, min, h, d) y se reinicia cada
  hora, día o mes en UTC, o nunca (`reset` = hour, day, month, none). El tiempo en que una
  entrada no tiene valor no suma nada; después de un reinicio del colector, el total continúa
  desde su último valor archivado en el mismo período.
- Las entradas son señales archivadas aquí: señales OPC UA en modo archive o both, u otras
  señales calculadas (un escaneo después). Las señales de PI Web API y CSV se leen solo a
  pedido, así que una fórmula no puede seguirlas. Una fórmula nunca se lee a sí misma, ni
  directamente ni a través de otras.
- El colector evalúa cada fórmula en el escaneo de la señal con los valores más recientes de sus
  entradas. Cualquier entrada mala, desconectada o faltante genera un hueco; cualquier entrada
  incierta vuelve incierto el resultado. Las fuentes que no informan calidad cuentan como buenas.
- La fórmula se puede cambiar en la página de la señal o en el CSV de la lista de señales
  (columna `address`).
