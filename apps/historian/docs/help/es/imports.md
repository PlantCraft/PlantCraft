# Importaciones

**Importaciones** carga archivos CSV y Excel en el archivo histórico: análisis de laboratorio,
una exportación de otro sistema, una hoja de cálculo. Una importación lee sus siguientes archivos
de la misma manera, y puede **repetirse desde una carpeta**: cada archivo nuevo que llega allí se
lee cada día, o con más frecuencia, en las mismas señales.

## Importar un archivo

1. Presione **Importar CSV** y elija el archivo (hasta 200 MB). Historian lo verifica de
   inmediato y todavía no escribe nada.
2. Defina la **zona horaria** de las horas escritas sin desfase. Las horas con desfase o `Z` se
   leen tal como están escritas. Todo se guarda en UTC.
3. Lea la verificación: formato, período, líneas, valores y señales, y luego los **errores** (el
   archivo no se puede importar) y las **notas** (se puede, pero revise primero). Cada problema
   lista sus líneas.
4. Ponga un nombre a la importación y presione **Importar**. El colector escribe los valores, un
   archivo a la vez; el estado muestra **En espera** mientras el archivo está en la cola, y luego
   **Escribiendo valores** con una barra de progreso. La **Cola** de la suite muestra lo mismo.
   Después, el archivo subido se elimina: los valores se quedan en el archivo histórico. Un
   archivo que sigue en espera se puede cancelar (**Cancelar el archivo en espera**); uno que se
   está escribiendo no se detiene.

## El siguiente archivo, y la repetición desde una carpeta

**Importar el siguiente archivo** lee un archivo nuevo como se leyó el último archivo de la
importación (separador, columnas, formato de hora, zona horaria), en la misma importación: los
tags nuevos se vuelven señales, y los valores en una hora ya importada se reemplazan.

**Repetir desde una carpeta** hace eso por sí solo. Indique un archivo, o un patrón como
`/csv/lab/*.csv`, dentro de las carpetas que el administrador habilitó para las fuentes CSV
(`HISTCRAFT_CSV_DIRS`), y con qué frecuencia revisarlo (de cada 15 minutos a cada día). Cada
archivo de allí que sea nuevo o haya cambiado se lee y se escribe, y aparece en la cola mientras
tanto; un archivo que no cambió no se vuelve a leer, y un archivo con errores se omite y se
nombra bajo el estado de la importación. Los archivos solo se leen, nunca se mueven ni se
cambian. Las señales conservan sus nombres (`import-3:LAB-101.DENSITY`), así que los gráficos y
los algoritmos que las usan siguen funcionando. Una importación que se repite también aparece en
Fuentes. **Dejar de repetir** conserva todos los valores escritos.

## Formatos

| Formato | Columnas |
| --- | --- |
| Ancho | La hora y luego una columna por tag. |
| Largo | La hora, el tag, el valor y, de forma opcional, la calidad (`good`, `uncertain`, `substituted`, `bad`). |

El separador (`,` `;` tabulación `|`) y una coma decimal se detectan a partir del archivo. Las
horas pueden estar en ISO 8601, `dd/mm/yyyy hh:mm` (`mm/dd` cuando una primera parte es mayor que
12) o epoch de Unix en segundos o milisegundos. Las celdas vacías y marcas como `NA`, `#N/A`,
`null` o `-` son huecos. Una columna que es mayormente texto se vuelve una señal de texto.

Los **errores** bloquean la importación: horas ilegibles, texto en una columna numérica, líneas
sin tag, calidades desconocidas, columnas duplicadas o sin nombre. Las **notas** no la bloquean:
horas repetidas (prevalece el último valor), horas a más de un día en el futuro, cómo se leyó una
fecha día/mes, un archivo importado antes.

## Señales y conservación

Cada importación es una fuente propia (`import-1`, `import-2`, ...) con una señal por tag, en
modo archive. Sus valores se conservan hasta que se elimina la importación, salvo que a una señal
se le asigne su propia retención. La lista conserva cada importación con quién la cargó y cuándo.

**Eliminar** borra la importación, sus señales y todos los valores que trajo, después de que
usted escribe su id. No se puede deshacer. Solo Ingeniería importa y elimina.
