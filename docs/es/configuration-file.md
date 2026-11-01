# Archivo de configuración

El **archivo de configuración** (el mapa de la planta) configura una instalación de una vez:
sus fuentes de datos, las señales en uso, el árbol de activos y los lazos, en un solo
archivo Excel o JSON. Úselo para arrancar una planta o para copiar una instalación a
otra. El trabajo diario sobre fuentes y señales (explorar tags, elegir qué guardar, su
histórico) se hace en la app **Historian**; el árbol de activos solo se mueve con
**Activos › Importar** y **Exportar**.

> Desde el 2026-10-24 el archivo de configuración no tiene página en PlantCraft (el responsable
> lo encontró poco claro al lado de la importación de activos, y una carga sobre una planta en uso
> era riesgosa). Se mantiene para configuraciones por script y para copiar una instalación a
> otra, a través de la API con una sesión de administrador:
> `GET /api/map/template.xlsx` o `/api/map/export.json`, luego
> `POST /api/map/preview?filename=<file>` y `POST /api/map/apply?filename=<file>`
> con el archivo como cuerpo (`ci/bench/suite_bench.py` hace exactamente esto). En la
> interfaz, el árbol de activos se importa en **Activos › Importar**, y allí se puede deshacer la
> última importación; las fuentes y las señales pertenecen a Historian.

## El archivo

El archivo tiene cuatro listas: descargue la plantilla, o exporte la configuración
actual, complétela, véala en vista previa y aplíquela.

- **Excel (.xlsx)**: una hoja por lista, con los nombres de las columnas en la primera
  fila. La hoja de léame de la plantilla explica cada columna. También se aceptan hojas con
  nombres en portugués (`fontes`, `ativos`, `sinais`, `malhas`).
- **JSON**: un objeto con las listas `sources`, `assets`, `signals` y `loops`.
- **CSV**: una sola lista, con el nombre de la hoja como nombre del archivo (`signals.csv`,
  `assets.csv`...).

### `sources`

| Columna | Obligatoria | Qué es |
| --- | --- | --- |
| `source_id` | sí | Identificador usado en la hoja `signals`. `scenario` es la fuente del escenario (solo lectura). |
| `name` | sí | Nombre que se muestra en la plataforma. |
| `type` | sí | `opcua`, `pi_web_api` o `csv`. |
| `endpoint_url`, `namespace_uri` | OPC UA | Dirección del servidor y namespace de los NodeIds. |
| `base_url`, `server` | PI | Dirección de PI Web API y nombre del PI Data Archive. |
| `path` | CSV | Ruta del archivo en el servidor. |
| `auth_type` | | OPC UA: `anonymous` o `basic`. PI: `kerberos`, `ntlm` o `basic`. |
| `username`, `password_env` | | Nombre de usuario y la variable de entorno que contiene la contraseña. Nunca escriba la contraseña en el archivo. |
| `timeout_seconds` | | Tiempo máximo de cada lectura. |
| `tags` | PI | Los tags de la fuente separados por `;`. |

### `assets`

| Columna | Obligatoria | Qué es |
| --- | --- | --- |
| `asset_id` | sí | Identificador sin espacios (`U-200`, `B-201A`). |
| `name` | sí | Nombre que se muestra en el árbol. |
| `kind` | sí | Tipo de activo: `unit`, `area`, `equipment`, `loop` u otro tipo registrado en la plataforma. |
| `parent_id` | | Activo padre; vacío: directamente bajo la instalación. |
| `description` | | Descripción libre. |
| `attributes` | | Atributos del activo: en JSON, un objeto (`{"power_kw": 75}`); en el libro, cada columna extra de la hoja. Todavía no se guardan: la vista previa avisa cuáles se ignoraron. |

### `signals`

| Columna | Obligatoria | Qué es |
| --- | --- | --- |
| `tag` | sí | El tag en la fuente (NodeId de texto en OPC UA, punto en PI, columna en CSV). |
| `source_id` | | La fuente del tag; vacío: la fuente del escenario. |
| `name`, `unit` | | Nombre legible y unidad de ingeniería. |
| `asset_id` | | Activo al que pertenece la señal. Un tag puede aparecer en varias filas, una por activo. |
| `role` | | El rol de la señal en el activo (`pv`, `pressure`, `vibration`...). |
| `monitor` | | `yes`/`no`: la plataforma sigue la señal. Vacío: sí. |

### `loops` (lazos de control)

| Columna | Obligatoria | Qué es |
| --- | --- | --- |
| `loop_id` | sí | Tag del lazo (`FIC-2001`); también es el id del activo del lazo. |
| `name` | sí | Nombre del lazo. |
| `asset_id` | | Activo donde está el lazo en el árbol (el equipo). Vacío: bajo la unidad y el área. |
| `area`, `unit`, `service` | | Área (agrupa en los paneles), unidad de proceso y descripción corta. |
| `pv` | sí | Tag de la variable de proceso. |
| `sp`, `op`, `mode`, `secondary` | | Tags del setpoint, la salida, el modo y una variable secundaria. |
Cada lazo se convierte en un activo de tipo `loop` con sus señales por rol, así cada
app de la suite lo encuentra: Analytics lo analiza en su próxima ronda. Cómo se analiza un
lazo (`protocol`, `loop_type`, `criticality`, `enabled`) se define en
Analytics; esas columnas, cuando están, aquí se ignoran con una advertencia. Un lazo
que viene del archivo del escenario se cambia en ese archivo, no por el mapa.

### Vista previa, aplicar y volver a importar

La vista previa cuenta, por hoja, lo que se va a crear, cambiar o quedar igual,
y lista los problemas con hoja y fila (en el libro, la fila 2 es la primera
después del encabezado):

- Los **errores** bloquean la importación: columna obligatoria vacía, tipo de activo o de fuente
  no válido, fuente o activo que no existe, un lazo sin `pv`, el mismo tag
  con dos fuentes.
- Las **advertencias** no bloquean: tag que no existe en la fuente, activo padre
  desconocido (el activo va bajo la instalación), contraseña que todavía hay que
  escribir, atributos y configuración de lazos ignorados.

**Aplicar** (solo administradores) escribe todo de una vez. Importar de nuevo el mismo archivo
no cambia nada. Lo que no está en el archivo queda como está; solo con la
opción **Quitar lo que no está en el archivo** la plataforma quita las fuentes
agregadas, los activos hechos a mano, los vínculos de señales y los lazos de un mapa que el
archivo no lista (los lazos del escenario nunca se quitan).

Para editar en Excel: **Exportar el mapa actual (Excel)**, edítelo y vuelva a importarlo.
Sin cambios, la vista previa dice que no cambia nada.

## Armar el mapa a partir de los manuales con un modelo de lenguaje

El camino más corto para una planta nueva suele ser: reunir los manuales y las listas de E/S
de los equipos, pedirle a su asistente de IA que arme el JSON y verificar el resultado
en la vista previa antes de aplicarlo. Para el árbol de activos, **Activos › Importar › Copiar como
prompt** pone un prompt listo en el portapapeles: el formato del archivo, un ejemplo,
los tipos de activo de esta instalación y las reglas que debe seguir la respuesta. Para un
mapa completo, el mismo tipo de prompt viene de la API (`/api/prompts/plant-map`).

El botón solo llena el portapapeles: no se envía nada a ningún lado. El prompt nunca
lleva la dirección, el nombre de usuario ni la contraseña de una fuente de datos; las fuentes se
configuran en Configuración, y al asistente solo se le piden activos, señales, lazos y relaciones.

Luego vea el JSON en vista previa (Activos › Importar, o `/api/map/preview`) y léalo con cuidado:
las advertencias sobre tags que no existen en la fuente suelen ser errores de lectura
del modelo.

## Para quien hace el despliegue

- Las fuentes agregadas viven en la tabla `data_sources` de la base de datos; las señales
  en uso y la fuente de cada tag, en `signal_routes`. La clave que cifra
  las contraseñas está en `sources.key` al lado de la base de datos (o en el archivo nombrado
  por `PLANTCRAFT_SOURCES_KEY_FILE`). Sin la clave, las contraseñas guardadas se deben
  escribir de nuevo.
- Cada lectura de datos va a la fuente dueña de cada tag; los tags sin dueño
  se leen de la fuente del escenario, exactamente como antes. Las fuentes OPC UA y PI
  agregadas usan la misma caché local del histórico que la fuente del escenario.
- Leer y escribir libros de Excel usa el paquete `openpyxl` (el grupo de dependencias
  `server`).
