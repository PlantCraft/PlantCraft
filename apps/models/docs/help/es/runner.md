# El ejecutor Modelica (administradores)

Models no compila ni ejecuta modelos en su propio contenedor. Entrega cada verificación, diagrama,
simulación y exportación al **ejecutor Modelica**, un contenedor separado con OpenModelica 1.24, la
Modelica Standard Library 4.0.0 y OMChemSim, la biblioteca abierta de procesos químicos (cargada
solo para un proyecto que la usa):

- **Ninguna red** (`network_mode: none`): no puede llegar a la planta, a PlantCraft ni a internet.
- **Ningún secreto**: ninguna clave de app, ningún token, ninguna base de datos.
- Sistema de archivos raíz de **solo lectura**, sin capacidades de Linux, con su propio usuario
  (uid 10011).
- **Límites**: CPU, memoria y número de procesos en el archivo compose; cada trabajo tiene un
  límite de tiempo (2 minutos para una verificación o un diagrama, 10 para una simulación o una
  exportación), un límite de memoria y un límite de tamaño de archivo, y se ejecuta en su propio
  grupo de procesos, que se termina al llegar al límite de tiempo.

Models y el ejecutor comparten solo una carpeta de trabajos: Models escribe un trabajo (los archivos
del modelo y qué hacer), el ejecutor responde con los resultados. Models verifica cada trabajo antes
de que salga (sin código `external`, sin funciones de archivos ni del sistema), y el ejecutor lo
vuelve a verificar.

## Los modelos compilados se conservan

Compilar un modelo (OpenModelica lo convierte en un programa C y lo compila) ocupa la mayor parte
del tiempo de una simulación: unos 5 segundos para los ejemplos, frente a una fracción de segundo
para ejecutarlo. El ejecutor conserva los últimos 32 modelos que compiló para estudios en su propio
`/tmp` (nunca en la carpeta de trabajos, en la que Models puede escribir): el siguiente lote de un
estudio, o el siguiente paso de una optimización, con los mismos archivos, modelo y configuración
de la simulación, ejecuta el programa que ya tiene y solo cambia los parámetros. Cualquier cambio en
un archivo vuelve a compilar. Un reinicio del ejecutor lo vacía. `--cache ""` (o
`MODELCRAFT_RUNNER_CACHE=`) lo desactiva.

## Su estado

El Resumen muestra si el ejecutor está disponible, su versión de OpenModelica y su biblioteca. El
ejecutor escribe una señal de vida cada 10 segundos; cuando se detiene, Models lo indica, mantiene
la edición disponible y rechaza verificaciones y simulaciones hasta que vuelva. La cola de
simulaciones se guarda en la base de datos: las simulaciones que estaban en ejecución cuando Models
se reinició vuelven a esperar en la cola (una exportación de FMU que estaba en curso se marca como
fallida).

## Configuración

| Variable | Por defecto | Significado |
|---|---|---|
| `MODELCRAFT_RUN_WORKERS` | `2` | Trabajos entregados al ejecutor al mismo tiempo (una simulación rápida o un lote de un estudio). Dimensiónelo según los núcleos que puede usar el ejecutor: aproximadamente la mitad de los de la máquina |
| `MODELCRAFT_RUN_BATCH` | `10` | Simulaciones de un estudio compiladas una vez y ejecutadas una después de otra en un solo trabajo |
| `MODELCRAFT_STUDY_MAX_RUNS` | `500` | El máximo de simulaciones que puede contener un estudio (la página de nuevo estudio advierte por encima de 100) |
| `MODELCRAFT_CHECK_SECONDS` | `120` | Límite de tiempo de una verificación o un diagrama |
| `MODELCRAFT_RUN_SECONDS` | `600` | Límite de tiempo de una simulación rápida o una exportación, y de la simulación de un estudio que no define ninguno |
| `MODELCRAFT_MAX_RUN_SECONDS` | `21600` | El límite de tiempo más largo que un estudio puede definir para cada simulación (6 horas) |
| `MODELCRAFT_ALLOW_EXTERNAL` | `false` | Permitir funciones `external` (código C) en los modelos. Déjelo desactivado salvo que se confíe en que cada editor ejecute código en el servidor |
