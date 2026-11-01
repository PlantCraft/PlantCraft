# Guía del usuario

PlantCraft es donde usted inicia sesión en la suite. Guarda lo que comparten todas las apps: las
personas, sus grupos y lo que cada una puede abrir, el árbol de activos, las acciones y los
mensajes. Las apps de la suite (Historian para los datos de la planta, Analytics, Alarms, Models,
Dashboards) se abren desde el menú. Nada en la suite cambia el proceso: solo lee los sistemas de la
planta.

## Iniciar sesión

Con el inicio de sesión activado, ingrese su nombre de usuario y su contraseña (pídalos al
administrador, que los crea en **Personas**). Una app de la suite que necesita que usted inicie
sesión lo envía aquí y, una vez dentro, lo lleva de vuelta adonde estaba. La demo no tiene
contraseña: el menú del perfil, abajo a la izquierda, cambia entre personas.

## Acceso

Lo que usted puede hacer depende de su nivel de acceso y de las apps habilitadas para usted:

- **Administrador**: todo, incluidas personas, grupos, apps y Configuración.
- **Ingeniería**: cambia el árbol de activos y edita en las apps.
- **Lectura**: ve los activos y abre sus apps en solo lectura; no cambia nada, y los botones de
  crear y editar no aparecen.
- **Solo dashboards**: para las pantallas de la sala de control.

Un administrador también puede limitarlo a una parte de la planta (una unidad, un área): entonces el
árbol de activos empieza en esos activos, y usted ve solo sus señales, lo que dicen las apps sobre
ellos y las acciones sobre ellos.

## Desk: su día

Después de iniciar sesión llega a **Desk**, su propio espacio de trabajo. **Hoy** es una página de
widgets que usted organiza: **Próximos días** (lo que tiene fecha, como el widget de agenda de un
teléfono), **Mis acciones** (las suyas, las de sus grupos o las que creó), **Notificaciones** (las no
leídas: alarmas, ejecuciones y cambios en sus acciones), **Mi día** (los pendientes de hoy),
**Sugerencias para hoy** (cada una con su motivo; tómela, pospóngala o descártela), **Activos que
sigo** y **Mi equipo** (su grupo: quién está ausente o tiene trabajo atrasado). Cada app instalada
agrega sus propios widgets. **Personalizar**, arriba a la derecha, le permite arrastrar un widget por
su título, tirar de su esquina para cambiar su tamaño, configurarlo (el engranaje) y agregar el mismo
widget dos veces con otra configuración; cada persona mantiene su propia organización.

Las otras páginas de Desk: **Acciones**, **Agenda** (mes, semana, día o lista; haga clic o arrastre
para agregar un evento propio; arrastre una acción para cambiar su fecha límite; **Agregar una
agenda** importa un archivo `.ics` de Outlook o Google, o lo lee por enlace cuando un administrador
lo permitió en Configuración › Agendas), **Pendientes** (Mi día, Planificados, sus listas y las
listas compartidas de sus grupos; un pendiente tiene fecha, repetición, pasos y notas, y se convierte
en una acción cuando necesita a otra persona), **Notas** (privadas hasta que las comparte con
personas o grupos; encabezados, listas, una lista de verificación, `#` para mencionar un activo o una
acción, y una línea que se convierte en un pendiente o una acción; un evento suyo en la Agenda tiene
su propia nota) y **Equipo** (cómo está su grupo hoy: quién está ausente u ocupado, las acciones del
grupo en un tablero, la semana que viene y la nota de cambio de turno del día). **Seguir** en la
página de un activo trae sus alarmas y resultados a su Desk.

**Mensajes** y el **Asistente** están al pie del menú, encima de su nombre, en todas las apps: cada
uno se abre sobre la página en la que está y al cerrarlo vuelve a ella. Mensajes tiene dos
secciones: **Conversaciones** con personas y grupos, y **Notificaciones**, que se leen como una
bandeja de entrada de correo (alarmas, ejecuciones y cambios que otros hicieron en sus acciones;
abra una para leerla, archívela cuando esté atendida).

## PlantCraft y las apps

**PlantCraft**, última en la lista de apps, es la configuración de la suite: su **Resumen** responde
"¿está sana la instalación?", con widgets que usted organiza: **Apps en línea**, **Conexiones de
datos** (cada conexión de Historian), **Sistema** (problemas abiertos, disco libre, última copia de
seguridad, versión, quién inició sesión hoy) y, para los administradores, **Cambios recientes** del
registro de auditoría. **Personalizar** vuelve a agregar los demás: **Necesita atención**,
**Acciones abiertas**, **Lo peor primero**, **Sus apps** y los widgets que publica cada app instalada
(una app que no está instalada no agrega ninguno). Un tablero que usted organizó queda como lo dejó;
**Restaurar el valor por defecto** trae este. Activos, Configuración, Personas, Apps, Estado del
sistema, Copias de seguridad y Actualizaciones son las páginas de PlantCraft.

## Moverse por la suite

Cada app de la suite tiene el mismo menú a la izquierda: las páginas propias de la app, luego
**Apps** (cada app que usted puede abrir: primero Desk, luego en el orden en que fluyen los datos:
Historian, Analytics, Models, Alarms, View, y al final PlantCraft; un clic cambia de app). Su nombre
al pie abre el menú del usuario: tema claro, oscuro o el del sistema (una sola elección para todas
las apps), el idioma, **Ayuda**, **Hacer el recorrido**, **Acerca de** (la versión) y **Cerrar
sesión**; un clic en cualquier otro lugar lo cierra. **Contraer** pliega el menú a íconos.

## Fuentes y señales

Las fuentes de la planta (OPC UA, PI Web API o CSV), sus señales y su histórico viven en la app
**Historian**: agregue y pruebe una fuente, explore sus tags, elija las señales que se guardan y por
cuánto tiempo. Una señal en la página de un activo se abre allí.

## Activos

**Activos** muestra la planta en carpetas: sitio, unidades, áreas, equipos y lazos, cada uno con sus
señales. El árbol se abre hasta el nivel 2; **Abrir hasta el nivel** 1, 2, 3 o Todo, encima de él, lo
abre tan profundo como necesite (la elección se guarda en su navegador), y **Contraer todo** lo
cierra. **Importar** y **Exportar** (arriba en la página) mueven solo el árbol: los activos, sus
fichas, las señales que referencian y sus relaciones, en el JSON de PlantCraft, Excel, CSV, ISA-95
B2MML o PI AF XML. Una importación abre primero una página de revisión: el archivo como un árbol,
cada activo marcado como nuevo, cambiado, sin cambios o con un error, donde usted corrige un nombre,
un tipo o un lugar, o deja fuera una fila, antes de aplicar. **Copiar como prompt** en la página de
importación le explica el archivo a su asistente de IA, para que pueda armar el árbol a partir de los
documentos de la planta o de la exportación de otro sistema. **Última importación** en la página de
importación muestra quién importó qué y cuándo, y **Deshacer la última importación** la revierte una
vez: los activos que creó se quitan y las fichas que cambió vuelven a como estaban.

**Borrador de una planta nueva** (en la página de importación, administradores) escribe el primer
árbol por usted cuando todavía no hay un archivo de activos. Elija una fuente (sus tags, tal como los
explora Historian) o una lista de tags (`.csv` o `.xlsx` con una columna tag y, si los tiene,
descripción y unidades de ingeniería). Los nombres ISA-5.1 dan cada lazo (`FIC-1003`), sus señales
por rol (`.PV`, `.SP`, `.OP`, `.MODE`), su tipo y su transmisor y su válvula (`FT-1003`, `FV-1003`).
Con **Documents** instalado, las narrativas de control, el índice de P&IDs, las hojas de datos y los
manuales de la planta ubican cada lazo en su unidad y su área, en su equipo, con el tipo y la ficha
del equipo; cada fila muestra de dónde viene (documento, revisión, página y el fragmento). Con un
modelo de lenguaje elegido para **Borrador de planta** (Configuración › Modelos de lenguaje), los
lazos que siguen en duda los ubica el modelo a partir de los mismos fragmentos; todo lo que nombre y
las fuentes no nombren se deja fuera. El borrador se abre en la misma página de revisión: **Por
verificar** filtra las filas que no son seguras, y dejar fuera una unidad o un área deja fuera lo
que el borrador puso en ella. No se escribe nada hasta que usted aplica, y la importación se puede
deshacer.

**Primeros pasos en las apps.** Una vez aplicada una importación, la página lista lo que cada app
instalada puede iniciar sobre los activos que escribió: Historian recolecta sus señales, Analytics
monitorea sus lazos (su primera ronda inicia la línea base de cada lazo), Alarms hace un borrador de
dos reglas por unidad (un lazo en mal estado, una señal sin datos) desactivadas para que usted las
revise, y View dibuja un dashboard de resumen por unidad. Marque los que quiere y tómelos; cada uno
se hace como usted, con su acceso en esa app, y dice lo que hizo con un enlace. Tomado de nuevo
después de una importación posterior, un paso omite lo que ya hizo.

Las fuentes y las señales entran a través de Historian. Una señal puede estar referenciada por
varios activos (la PV de un lazo también es la medición de su transmisor); la pestaña **Señales** de
cada activo dice dónde más se usan sus señales. Busque por nombre o código, filtre por tipo, cree un
activo (administradores), muévalo bajo otro, o agregue un tipo propio. Un lazo es un activo cuyas
señales tienen los roles `pv`, `sp`, `op`, `mode` y `secondary`; las apps que analizan lazos los leen
desde aquí. Un activo que usted editó a mano nunca vuelve a cambiarlo el archivo del escenario ni un
mapa.

La página de un activo está en `/assets/<id>` (por ejemplo `/assets/FIC-101`); copie la dirección
para compartirla. Los enlaces antiguos `/plant/<id>` todavía la abren. Sus pestañas: **Resumen** (la
ficha al lado de las señales principales y lo que hay dentro), **Señales** (una tabla: cada rol de su
tipo y la señal que lo llena, o el hueco por vincular, luego las demás señales, con el último valor),
**Dentro de** (todo lo que está debajo), **Relaciones**, **Acciones** e **Historial**. La pestaña está
en la dirección (`?tab=signals`).

## Acciones

**Acciones** es un tablero con una columna por estado (abierta, en curso, bloqueada, terminada); cada
tarjeta dice cuánto tiempo lleva allí y cuándo vence. Las personas con rol de ingeniería arrastran
una tarjeta a otra columna para moverla; el trabajo terminado que debe salir del tablero se
**archiva**. Una tarjeta muestra el título, el comienzo de la descripción y el avance de la lista de
verificación. **Lista** muestra las mismas acciones como una tabla. Una tarjeta abre la página propia
de la acción: descripción, una **lista de verificación** (elementos marcados uno por uno, cada uno
con quién y para cuándo), de qué trata, historial y comentarios, y sus datos al lado. Escriba `#` (o
use **Mencionar**) para apuntar a un activo, una persona o una ejecución: se convierte en un enlace.
El nombre de una persona abre su página.

Una acción va a una persona, a un grupo o a ambos. Cada persona ve las acciones de las que es
responsable, que creó o en las que la mencionan, las de sus grupos y, cuando dirige un grupo, las de
los grupos de abajo; un administrador ve todas. **Mostrar** elige lo que lista el tablero: **Todo lo
que puedo ver**, **Asignadas a mí**, **Mis grupos** o **Creadas por mí**; filtre arriba por grupo,
persona, estado o texto.

## Mensajes

**Mensajes** guarda conversaciones entre personas y con especialistas. **Nueva conversación** elige
personas una por una, o un grupo completo de una vez. Cada grupo también tiene su propia conversación
(**Conversación del grupo** en la página del grupo): sus miembros son los del grupo, y siguen al grupo
a medida que las personas entran o salen de él.

Cada nombre abre la página de la persona: cargo, sector, unidad, cómo contactarla y las acciones de
las que es responsable. **Mi perfil**, en el menú del usuario, es donde cada persona mantiene el suyo.

**Tipos de activo**, una pestaña de **Activos**, dice qué registra cada tipo de activo: atributos,
roles de señal y lo que puede estar dentro de él (los administradores lo editan).

## Personas y grupos (administradores)

**Personas › Grupos** mantiene la organización como un árbol: departamentos, áreas, disciplinas y
equipos, cada uno bajo otro. El coordinador de un grupo es su líder y ve las acciones de cada grupo
de abajo. Una persona puede estar en varios grupos; elíjalos en la página del grupo o en la cuenta de
la persona.

## Personas y claves de las apps (administradores)

En **Personas** y **Apps › Claves de las apps**:

- cree una persona con un nombre de usuario, una contraseña inicial, un nivel de acceso y las apps
  que puede abrir (o todas las apps, incluidas las que se instalen después);
- dele a una persona en una app dada otro rol que el que da su nivel (solo lectura en Historian,
  ingeniería en Alarms), y complete su perfil;
- limite a una persona, o a todos los miembros de un grupo, a una parte de la planta: en **Activos
  que ve** (o en **Activos que ven los miembros** del grupo) elija las unidades o las áreas; ven esos
  activos, todo lo que está debajo de ellos, sus señales y lo que dicen las apps sobre ellos;
- cambie el nivel o las apps de una persona (tiene efecto de inmediato), restablezca su contraseña
  (sus sesiones abiertas terminan) o desactívela (su historial se mantiene);
- emita una **clave de app** para cada app de la suite. La app la usa para su trabajo en segundo
  plano, como las rondas de Analytics. La clave se muestra una sola vez: cópiela en la configuración
  `PLANTCRAFT_APP_KEY` de la app. Revoque una clave cuando se filtre o la app se mude.

## Configuración (administradores)

**Configuración** guarda lo que no tiene otro lugar: **Inicio de sesión corporativo**, el **Registro
de auditoría**, **Modelos de lenguaje**, el acceso de asistentes (MCP), los notebooks, las agendas y
el correo. **Estado del sistema**, **Copias de seguridad** (con su programación) y
**Actualizaciones** tienen sus propias páginas bajo Administración. Las personas, los grupos y los
especialistas están en **Personas**; las apps y las claves de las apps en **Apps**; los tipos de
activo en **Activos**.

## Modelos de lenguaje y especialistas (administradores)

Los especialistas son usuarios robot a los que las personas les escriben; responden a partir de lo
que publicaron las apps. Sin modelo de lenguaje responden con respuestas predefinidas. En
**Configuración › Modelos de lenguaje** un administrador agrega los servidores en los que se ejecutan
los modelos: un nombre, el formato (compatible con OpenAI para Ollama, vLLM, LM Studio, Azure y la
mayoría de los gateways, o Anthropic), la dirección, la clave si el servidor la necesita y la lista
de modelos que sirve. Cada modelo tiene un botón **Probar**. Un proveedor y un modelo son los de
por defecto de la instalación, y no se envía nada a ningún lado hasta que "Usar modelos de lenguaje"
esté activado. En **Personas › Especialistas** cada especialista responde con el de por defecto, con
un proveedor y un modelo elegidos para él, o solo con respuestas predefinidas.

## Demo

Una instalación hecha con `install.sh --demo` (o `--public-demo`, que además abre una cuenta `demo`
de solo lectura en la página de inicio de sesión) ejecuta el Simulator, una planta simulada de 50
lazos leídos por OPC UA, y una historia de demostración a través de las apps: lazos con una válvula
con fricción estática, una oscilación y un sensor que deriva en Analytics, alarmas, dashboards,
gemelos, modelos, acciones y conversaciones. Para escribir la historia de nuevo (nunca duplica
nada), ejecute en la carpeta de la instalación:

```bash
docker compose exec processcraft plantcraft demo seed
```

Desde un checkout del código fuente, `python run_opcua_demo.py` inicia la misma demo para
desarrollo (vea el README).
