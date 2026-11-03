# Glosario es

> **Estado:** revisado el 2026-11-02 contra el uso de los proveedores del sector (ver Fuentes). Toda traducción al español
> sigue esta tabla: una palabra, un sentido, en toda la suite, como en [glossary.md](glossary.md)
> y en paralelo con [translations-glossary-pt-BR.md](translations-glossary-pt-BR.md). Cambiar un
> término aquí es cambiarlo en todos los catálogos (`locales/es.json`).

## Reglas

- Español neutro de América Latina, técnico y directo, como un manual de ingeniería de procesos;
  sin voseo y sin regionalismos. Se trata de "usted" solo cuando no se puede evitar.
- Los nombres de los productos no se traducen: PlantCraft, Analytics, Historian, View, Alarms,
  Models, Documents, Desk, Notebooks, Simulator. Tampoco ids, código, unidades, tags
  (`FIC-101.PV`), nombres de archivo ni términos de API.
- Los botones van en infinitivo ("Guardar", "Eliminar"). Mayúscula solo en la primera palabra.
- Los campos `{nombre}` quedan iguales al inglés.
- Los términos de ISA-18.2 siguen el uso corriente en América Latina (reconocer, archivar,
  fuera de servicio).
- En caso de duda, vale el término que ya usan los proveedores del sector en español (Grafana,
  ThingsBoard, FUXA, Microsoft).

## Palabras de la suite

| Inglés | Español | Nota |
|---|---|---|
| Signal / Signals | Señal / Señales | nunca "punto" ni "variable" |
| Tag | Tag | solo la dirección de la señal en su fuente |
| Label | Etiqueta | |
| Derived signal / Calculated signal | Señal derivada / Señal calculada | |
| Asset / Asset type | Activo / Tipo de activo | |
| Role | Rol | |
| Target (de un resultado) | Objetivo | |
| Target (meta de desempeño o de atención) | Meta | |
| Result | Resultado | nunca "veredicto" |
| OK, Warning, Critical, Unknown | OK, Advertencia, Crítico, Desconocido | |
| Event | Evento | |
| Run | Ejecución | |
| Simulation | Simulación | |
| Queue | Cola | |
| Compute, Worker, Compute task | Cómputo, Worker, Tarea de cómputo | |
| Folder | Carpeta | |
| Group | Grupo | solo de personas |
| Library | Biblioteca | |
| Overview | Resumen | |
| Widget | Widget | |
| Panel | Panel | |
| Dashboard | Dashboard | |
| Report | Informe | |
| Trend | Tendencia | |
| Settings / Preferences | Configuración / Preferencias | |
| People | Personas | |
| System health | Estado del sistema | |
| Assistant / Specialist / Task | Asistente / Especialista / Tarea | |
| Alarm / Alert | Alarma / Alerta | |
| Source | Fuente | |
| Plant / Unit | Planta / Unidad | |
| Workspace | Espacio de trabajo | |
| Inbox | Bandeja de entrada | |
| Messages, Chats, Notifications | Mensajes, Conversaciones, Notificaciones | |
| Today, Actions, Calendar, To-do, Notes, Team | Hoy, Acciones, Agenda, Pendientes, Notas, Equipo | |
| Audit log | Registro de auditoría | |
| Backups, Updates, App keys | Copias de seguridad, Actualizaciones, Claves de las apps | |
| Schedule (de copias) | Programación | |
| Public link | Enlace público | |
| Sign in / Sign out | Iniciar sesión / Cerrar sesión | |
| Owner, Share, Help, Search | Responsable, Compartir, Ayuda, Buscar | |
| Editor / Viewer (roles) | Editor / Visualizador | como en Grafana |
| Operations (app) | Operación | |
| Request | Solicitud | |
| Process display | Pantalla de proceso | |
| Stat, Gauge, Bar gauge, Dial, Threshold | Estadística, Medidor, Medidor de barra, Cuadrante, Umbral | como en Grafana; "Cuadrante" para el dial |

## Control y lazos (Analytics)

| Inglés | Español |
|---|---|
| Loop / Control loop | Lazo / Lazo de control |
| Controller | Controlador |
| Setpoint (SP), Process variable (PV), Output (OP/MV) | Setpoint (SP), Variable de proceso (PV), Salida del controlador (OP/MV) |
| Valve | Válvula |
| Stiction | Fricción estática (stiction) |
| Oscillation | Oscilación |
| Tuning | Sintonía |
| Gain, Integral time, Derivative time | Ganancia, Tiempo integral, Tiempo derivativo |
| Manual / Automatic / Cascade | Manual / Automático / Cascada |
| Saturation | Saturación |
| Block, Algorithm, Monitor, Method | Bloque, Algoritmo, Monitor, Método |
| Finding / Check | Hallazgo / Verificación |
| Cadence / Recorded outputs | Cadencia / Salidas registradas |
| Wire / Gate | Conexión / Compuerta |
| Soft sensor | Inferencia (soft sensor) |
| Surge level | Nivel pulmón |
| Replay | Reejecución |

## Historian

| Inglés | Español |
|---|---|
| Scan | Escaneo |
| Deviation (compression) | Desviación |
| Max interval | Intervalo máximo |
| Retention | Retención |
| Step | Escalón |
| Archive | Archivo histórico |
| Backfill | Relleno retroactivo |
| Import / Export | Importación / Exportación |
| Collector / Compression / Rollup | Colector / Compresión / Agregación |

## Alarms (ISA-18.2)

| Inglés | Español |
|---|---|
| Acknowledge / Acknowledged / Unacknowledged | Reconocer / Reconocida / No reconocida |
| Shelve / Shelved / Unshelve | Archivar / Archivada / Desarchivar |
| Suppressed by design | Suprimida por diseño |
| Out of service | Fuera de servicio |
| Return to normal (RTN) | Retorno a normal (RTN) |
| Clear / Raise | Normalizar / Activar |
| Priority: Critical, High, Medium, Low | Prioridad: Crítica, Alta, Media, Baja |
| Rule / Silence / Journal | Regla / Silencio / Bitácora |
| Chattering / Standing (stale) alarm / Flood | Alarma repetitiva / Alarma permanente / Avalancha de alarmas |
| Deadband / Delay | Banda muerta / Retardo |
| Board (console) / DCS | Consola de operación / DCS |

## Models

| Inglés | Español |
|---|---|
| Model, Study, Simulation settings, Solver | Modelo, Estudio, Configuración de la simulación, Solver |
| Category, Indicator, Compile, Parameter | Categoría, Indicador, Compilar, Parámetro |
| Input / Output | Entrada / Salida |
| Steady state, Optimization | Estado estacionario, Optimización |
| Tracking, Parameter sweep | Seguimiento, Barrido de parámetros |
| Overshoot, Settling time | Sobreimpulso, Tiempo de establecimiento |
| Step (de tiempo) | Paso |

## Fuentes (revisión del 2026-11-02)

- Grafana, catálogo es-ES: `public/locales/es-ES/grafana.json` en github.com/grafana/grafana
  (Resumen, Configuración, Umbral, Medidor, Estadística, Advertencia, Visualizador, Silencios,
  Regla, Etiqueta).
- ThingsBoard, catálogo es-ES: `ui-ngx/src/assets/locale/locale.constant-es_ES.json` en
  github.com/thingsboard/thingsboard (Activo, Alarma, Reconocer, Reconocida, Advertencia, Crítico,
  Cola, Informe, Registro de auditoría, Severidad).
- FUXA (SCADA abierto), catálogo es: `client/src/assets/i18n/es.json` (Alarmas, Informe, banda
  muerta).
- "Archivar" para el *shelving* de ISA-18.2 sigue el término de Elipse en portugués
  (https://kb.elipse.com.br/arquivamento-e-gerenciamento-de-alarmes-no-e3alarm/): no se encontró un
  proveedor con el término en español, y "suprimir" queda para la supresión por diseño.
