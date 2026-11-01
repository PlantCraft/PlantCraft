# Primeros pasos

Una hora con la planta de demostración, app por app. Va a seguir un problema, una válvula con
fricción estática, desde la señal hasta la alarma, el dashboard, un modelo y un notebook, y va a ver
cómo las apps de la suite se lo pasan entre sí. Necesita una instalación con la historia de la demo
(`./install.sh --all-apps --demo`, vea [Instalar PlantCraft](../install.md)) y la contraseña del
administrador.

## La planta y la historia

La planta de demostración es el **Simulator**: un servidor OPC UA de 50 lazos de control en dos
unidades, U-100 y U-200, con fallas que simula a propósito. Cuatro válvulas tienen fricción estática
(FIC-1003, FIC-1102, FIC-1206, FIC-1214), algunos lazos de presión y temperatura oscilan (PIC-1002,
PIC-1202), la temperatura de salida del horno TIC-1209 deriva, y TIC-1104 sufre una perturbación
cíclica.

La historia llena la suite como si un equipo la hubiera usado durante tres semanas: Ana Lima, la
ingeniera de procesos, un técnico, operadores y un supervisor, sus conversaciones y acciones,
monitores ya en ejecución, dashboards, reglas de alarma, estudios de modelos y las conversaciones
con el asistente que guardaron. El visitante de la demo participa en las conversaciones del equipo
en Mensajes.

## 1. Iniciar sesión y encontrar su día (Desk)

Abra la dirección de la suite e inicie sesión como `admin`. Llega a **Desk**, el día de cada
persona:

- **Hoy** reúne lo que lo necesita a usted: notificaciones, acciones asignadas a usted, los eventos
  del día y los widgets que elija. **Personalizar** mueve y agrega widgets.
- **Acciones** guarda los seguimientos que abrió el equipo, como *Inspect the FIC-1003 recycle
  valve for stiction*. Abra una para ver su objetivo, su responsable y su historial.
- **Agenda**, **Pendientes**, **Notas** y **Equipo** son el resto del día: reuniones, su propia
  lista, notas y quién está de turno.

Al pie de la barra lateral están los cuatro botones rápidos que comparten todas las apps:
**Mensajes** (conversaciones con personas y especialistas), **Notificaciones** (lo que necesita a
una persona), **Asistente** (la conversación de IA de la página en la que está) y **Cola** (lo que
se ejecuta en segundo plano, app por app).

## 2. El mapa de la planta (PlantCraft)

Abra **PlantCraft** en el menú de apps y luego **Activos**. El árbol es la planta: el sitio, sus
unidades, áreas, equipos y lazos. Abra **FIC-1003**: sus señales aparecen por **rol** (`pv`, `sp`
y `op` del lazo), así cada app sabe cuál señal es la medición y cuál es la salida a la válvula sin
que se lo digan de nuevo.

Todas las apps leen el mismo árbol. Cuando agrega una unidad o un lazo aquí, Analytics, Alarms y
View lo ven de inmediato. Un mapa completo de la planta se puede cargar desde Excel o JSON
([Archivo de configuración](configuration-file.md)).

## 3. Los datos (Historian)

Abra **Historian**. **Fuentes** lista de dónde vienen los datos: aquí, el servidor OPC UA del
Simulator; en una planta, una fuente PI Web API, OPC UA, MQTT, Modbus TCP, SQL o CSV. **Señales**
lista cada señal archivada, con su configuración de escaneo y compresión. Abra `FIC-1003.OP` y mire
un día de ella: la salida a la válvula se mueve en escalones en lugar de suavemente, el primer
indicio de fricción estática.

Historian es de solo lectura hacia la planta. Las **señales calculadas** derivan señales nuevas de
otras (una diferencia, una razón, un filtro), **Importaciones** trae archivos una vez o cada vez
que llegan a una carpeta, y **Exportaciones** saca datos a CSV.

## 4. Vigilar los lazos (Analytics)

Abra **Analytics**. Ejecuta **algoritmos**, hechos de **bloques**, sobre los activos y las señales
de la planta, y publica **resultados**: un nivel (OK, Advertencia, Crítico o Desconocido), una
puntuación de 0 a 100 y una frase que dice por qué.

1. **Monitores** lista lo que se ejecuta por su cuenta: *Control loop performance* evalúa cada lazo,
   *Signal quality* cada señal, y *Furnaces* ejecuta el modelo de los hornos al lado de la planta.
2. **Resultados** muestra lo que concluyeron, por monitor, luego por objetivo, luego en el tiempo.
   Abra FIC-1003: su resultado nombra la fricción estática y muestra la evidencia, la tendencia y la
   firma de la válvula.
3. **Algoritmos** muestra cómo se llega a un resultado. Abra *Flow loop* y el editor lo dibuja como
   bloques conectados entre sí. **Probar** lo ejecuta ahora sobre un lazo, sin guardar nada;
   **Copiar como prompt** lo convierte en un prompt para revisarlo o ampliarlo con cualquier
   asistente de IA.
4. El modelo del horno también es un algoritmo: un modelo de proceso al lado de la planta que dice
   cuándo la TIC-1209 medida se aleja de lo que predice el modelo.

Analytics nunca toca la planta. Lee, evalúa y lo dice, y cuando no puede evaluar (una señal
congelada, un hueco, muy poco movimiento) dice Desconocido y por qué, en lugar de adivinar.

## 5. Alarms

Abra **Alarms**. Las **Reglas** convierten señales y resultados de Analytics en alarmas y alertas,
en las palabras de ISA-18.2: una regla es **Simple** (un límite con banda muerta y retardo),
**Bloques** o **Python**. Abra *PIC-1202 pressure high* o *Loop critical for over 1 h* para ver
cada tipo.

- **Alarmas** es la lista de lo que está activo ahora. **Reconozca** una; **Suprimir** la oculta
  por un tiempo con un motivo. Una alarma también llega a **Notificaciones**, con los mismos
  botones.
- **Eventos** lista lo que publicaron las apps (un resultado que cambió de nivel, una ejecución que
  falló) y convierte uno en regla con un clic.
- **Historial** guarda la bitácora, lo que se envió, y **Desempeño**: alarmas por hora, avalanchas,
  las alarmas más frecuentes, las alarmas permanentes, frente a las metas de ISA-18.2.

## 6. Dashboards, informes y tendencias (View)

Abra **View**. Los **dashboards** están hechos de **paneles** (valor, indicador, tendencia, gráfico
de barras, tabla, dispersión, texto):

- *Plant overview* tiene un **enlace público**: cualquiera que lo tenga ve el dashboard sin iniciar
  sesión, en solo lectura.
- *Control room* pasa sus tres páginas cada minuto, para una pantalla de pared.
- *Loop detail* tiene una **variable**: elija otro lazo arriba y todos los paneles lo siguen.

**Tendencias** dibuja cualquier señal en cualquier período y guarda la vista. **Informes** convierte
un dashboard en un documento según una programación (*U-100 daily report*, *Control loops weekly
performance*) y lo exporta como Word, HTML o Markdown.

## 7. Modelos y simulaciones (Models)

Abra **Models**. Un modelo es un **diagrama de bloques** (con Modelica por debajo) que usted dibuja
desde la biblioteca o escribe como código.

1. **Modelos** lista los ejemplos. Abra el tanque: arrastre un bloque, conéctelo, cambie un
   parámetro.
2. **Simular** inicia una **simulación**; **Simulaciones** lista todas las simulaciones y la cola.
   Una de las simulaciones de la historia se alimenta con la última hora de un lazo real y se
   compara con él.
3. Los **estudios** ejecutan un modelo muchas veces (**Nuevo estudio**). *Tank size* y *Heat
   exchanger area* varían un parámetro sobre una grilla; abra uno y compare las curvas.
4. **Exportar FMU** empaqueta un modelo para que Analytics pueda ejecutarlo al lado de la planta,
   como hace el ejemplo del horno.

El trabajo pesado se ejecuta en **workers de cómputo**, lejos de las apps: un administrador los ve
en Configuración › Cómputo y puede agregar máquinas ([Workers de cómputo](../compute.md)).

## 8. Notebooks

Abra **Notebooks** para usar Python con los datos de la planta: JupyterLab en el navegador, o el
mismo notebook en su propia computadora con el kit de PlantCraft Notebooks. Los ejemplos leen
señales de Historian, resultados de Analytics y simulaciones de Models con pocas líneas, como la
persona que los ejecuta ([Notebooks](notebooks.md)).

## 9. Preguntar al asistente

En cualquier página, el botón **Asistente** ofrece primero las **tareas** de esa página: *Why did
this alarm fire?* en una alarma, *Which alarms should we fix first?* en Desempeño, *Explain this
dashboard* en View, *Help me create a new block* en Analytics. Lee solo lo que usted puede leer, a
través de la misma API y los mismos permisos que usted tiene, y nunca escribe: una creación vuelve
como una propuesta que usted confirma.

El asistente necesita un modelo de lenguaje, y la suite viene sin ninguno activado. Hasta que un
administrador configure uno en Configuración › Modelos de lenguaje, el panel lo dice, y el
especialista Valve en Mensajes responde con respuestas predefinidas. Vea
[el asistente](../assistant.md).

## 10. Hágala suya

| Para | Vaya a |
|---|---|
| Conectar su planta | Historian › Fuentes, luego PlantCraft › Activos ([Guía del usuario](user-guide.md)) |
| Cargar el mapa de la planta desde una planilla | [Archivo de configuración](configuration-file.md) |
| Agregar personas, grupos y quién abre cada app | PlantCraft › Personas ([Guía del usuario](user-guide.md)) |
| Poner su propio algoritmo en sus lazos | Analytics › Algoritmos › Nuevo, luego Monitores › Nuevo |
| Hacer copias de seguridad, actualizar, verificar los certificados | [Ejecutar la suite](running-the-suite.md) |
| Crear una app propia | La [plantilla de app](../../templates/app) |

Las palabras usadas aquí se definen una sola vez en el [glosario](../glossary.md); las ideas detrás
de ellas están en [Conceptos](concepts.md).
