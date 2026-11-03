# Informes

Un **informe** es un documento sobre un período, escrito como un notebook: celdas de texto en
Markdown, los mismos paneles que un dashboard (KPIs, medidores, tendencias, barras, tablas,
dispersión) y los eventos que escribieron las apps (alarmas, hallazgos de Analytics). View lo
convierte en un **PDF** según una programación y lo envía a personas y grupos en **Mensajes ›
Notificaciones**, con el PDF a un clic. Cada PDF generado se conserva, así lo que se envió se puede
leer de nuevo tal como era. También se descarga como **Word**, como **página web** y como
**Markdown**, y se abre mediante un **enlace público**.

Cada dashboard puede tener su informe al lado, en la misma carpeta: **Nuevo informe › Comenzar
desde un dashboard** convierte sus páginas en títulos y sus paneles en celdas.

## El período

Cada sección de un informe lee el período del informe, que termina cuando se genera el informe: un
informe generado todos los días a las 06:00 sobre **las últimas 24 horas** abarca de las 06:00 del
día anterior a las 06:00 (el día del turno). En un informe, los paneles no tienen ventana propia.

Un informe programado puede en cambio abarcar **períodos completos del calendario**: ayer de
medianoche a medianoche, la semana pasada de lunes a domingo, las dos semanas antes del lunes, el
mes pasado o el trimestre pasado, según el reloj de la instalación. Cada panel lee entonces el
período que se cerró, sea cual sea el momento en que se genera el informe: un informe mensual
enviado el día 3 sigue abarcando del primer al último día del mes anterior.

## Programación y destinatarios

**Configuración** define:

- **Repetir**: todos los días, todas las semanas o cada dos semanas (en un día de la semana), todos
  los meses o cada trimestre (el día 1 a 28), a una hora de la zona horaria de la instalación. Los
  informes *No programados* se generan solo cuando alguien lo solicita.
- **Abarca**: el período, de 1 hora a un año. Cambiar la repetición sugiere un período
  correspondiente (un día, 7, 14, 30 o 90 días). **Períodos completos del calendario** abarca en
  cambio el último día, semana, dos semanas, mes o trimestre cerrado.
- **También cuando un evento termina un lote o un arranque**: cada evento nuevo del tipo indicado en
  **Se genera cuando** (sobre el activo de **Solo sobre**, o cualquiera) genera un informe sobre el
  lote que termina: desde el último evento del tipo indicado en **Desde** sobre el mismo activo, si
  no desde el inicio que trae el evento, si no el período de arriba antes de él; como máximo 31
  días. Cada lote se informa una sola vez.
- **Enviado a**: personas y grupos de la plataforma. Reciben una notificación por envío; solo
  quienes pueden ver la carpeta del informe lo abren. **También por correo electrónico** agrega un
  correo donde PlantCraft envía correos y la persona lo permite.

Los próximos envíos aparecen en la agenda de Desk, y PlantCraft lista la programación junto con
la de las otras apps.

## Construir un informe

**Editar** abre el editor en la propia página. Agregue celdas al final, o debajo de cualquier celda
con su **+**:

- **Texto**: Markdown, escrito en el lugar con su vista previa al lado (doble clic en un texto para
  escribir en él; Shift+Enter termina). `#` a `####` son títulos de cuatro niveles, luego párrafos,
  **negrita**, *cursiva*, listas (`-`, `1.`), tablas (`| a | b |`), citas (`>`) y enlaces. Los
  títulos son las **secciones** del informe: la navegación al costado de la página, los marcadores
  del PDF, el panel de navegación de Word y el menú lateral de la página web.
- **Panel**: un gráfico, KPIs o una tabla, construido en el mismo editor que los paneles de un
  dashboard. Un informe nombra sus señales y activos (sin variables, sin paneles repetidos).
- **Eventos**: hasta 10 tipos de eventos de las apps instaladas; la sección cuenta cada tipo en el
  período y lista los más recientes (hasta 100).
- **Salto de página**: el PDF comienza una página nueva ahí.
- **Sección del asistente**: texto que el modelo de lenguaje escribe a partir de los últimos
  resultados de lazos, de calidad de señal y de alarmas y de los eventos del período sobre los
  activos que usted elige (márquelos, o descríbalos y el modelo los elige). **Requisitos (el
  prompt)** dice qué escribir y se puede editar; los comentarios sobre una edición van al modelo,
  que propone los próximos requisitos, conservados versión por versión. Cada número, fecha o
  hallazgo que el texto afirma cita su hecho como una nota al pie numerada, y **Evidencia** lista
  qué es cada uno: un resultado con su estado, puntuación y hora, un evento con su hora y resumen,
  o los conteos del período. Un tag o una fecha que los hechos no dan se señala, y una cita de un
  hecho que el modelo no recibió se descarta. La sección está desactivada hasta que un
  administrador asigna un modelo a los usos `report-write` y `report-tune`.

Mueva las secciones hacia arriba y hacia abajo; los paneles y los eventos pueden tener **medio
ancho**, y dos secciones de medio ancho seguidas quedan lado a lado. Mientras usted edita, los
paneles leen con su propio acceso; el PDF lee con el de View, como un dashboard publicado.

## Generar, descargar y enviar

- **Descargar** lee el informe ahora y lo guarda en su computadora; nadie más lo recibe:
  - **PDF**: para imprimir y conservar; también se guarda en **Enviados**.
  - **Word (.docx)**: para modificar y pasar a otros. Los títulos son los propios Título 1 a 4 de
    Word, las tablas son tablas de Word, los gráficos son imágenes. Se abre en Word, LibreOffice y
    Google Docs.
  - **Página web (.html)**: un archivo que se abre en cualquier lugar, sin conexión: las secciones
    al costado, y gráficos que muestran el valor de cada línea bajo el puntero (como lo hace
    Grafana); haga clic en una línea de la leyenda para ocultarla.
  - **Markdown (.md)**: texto plano para una wiki, un notebook o un ticket: el texto tal como se
    escribió y cada panel como sus valores.
- **Enviar ahora** lo genera y lo envía a sus destinatarios, como lo haría la programación.
- **Enviados** lista cada PDF generado: cuándo, qué abarcó, cómo (programado, enviado, descargado),
  a cuántas personas llegó y si alguna sección no se pudo leer. Una sección que no se puede leer
  dice por qué en el PDF y el resto del informe se genera igual; un informe que no se puede generar
  en absoluto es un envío fallido, y se avisa a los administradores de la plataforma.

## Enlaces públicos

**Compartir** crea un enlace que abre el informe como su página web, leída de nuevo cada vez que se
abre, sin iniciar sesión: para un colega sin cuenta o una pantalla. Un enlace abre solo ese informe
y deja de funcionar cuando se revoca o se elimina el informe (vea *Enlaces públicos*).

## Carpetas

Los informes y los dashboards comparten las mismas carpetas, que dicen quién ve y quién edita lo
que contienen; **Nueva carpeta** está en ambas páginas. **General** no es una carpeta: contiene lo
que está fuera de toda carpeta, abierto a todos, así que no tiene configuración y ninguna carpeta
puede tomar su nombre. Una copia de un informe comienza sin programación, así nunca envía dos veces
lo que envía el original.
