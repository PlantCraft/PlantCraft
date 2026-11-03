# Fuentes

Una fuente es un sistema de planta que Historian lee: un servidor OPC UA, un PI Web API, archivos
CSV o, a través del gateway, un broker MQTT, un dispositivo Modbus TCP o una base de datos SQL, o
los nodos edge de un broker Sparkplug B.
Las señales calculadas (vea Señales) tienen una fuente propia, `calc`, creada con la primera de
ellas. Las señales derivadas de las apps tienen una fuente propia, que solo escribe la app. Solo
los administradores agregan, cambian o eliminan fuentes.

- **Endpoint**: `opc.tcp://host:port/path`, la URL base de PI Web API, o el archivo o patrón CSV
  (`/csv/lab/*.csv`).
  Historian solo lee: Read, Browse y HistoryRead de OPC UA, GET de PI Web API. Nunca escribe en
  un sistema de planta.
- **Inicio de sesión**: anónimo, o un nombre de usuario con contraseña. Una contraseña escrita se
  guarda cifrada y nunca se vuelve a mostrar; también puede venir de una variable de entorno
  `HISTCRAFT_SECRET_*`.
- **Seguridad** (OPC UA): Ninguna, Firmar, o Firmar y cifrar, con la política que ofrece el
  servidor (Basic256Sha256, Aes128_Sha256_RsaOaep o Aes256_Sha256_RsaPss). Descargue el
  certificado de Historian desde el formulario y agréguelo a la lista de confianza del servidor.
  La primera **Prueba** muestra el certificado del servidor (su SHA-256, sujeto y fechas):
  compárelo con lo que ve el administrador del servidor y luego presione **Confiar**. A partir de
  entonces, se rechaza un servidor que presente otro certificado.
- **Calidad**: OPC UA y PI informan la calidad de cada valor. Los valores inciertos se archivan y
  aparecen sombreados en la tendencia de la señal; los valores malos son huecos. Con OPC UA
  también se conserva el código de estado (como `UncertainLastUsableValue` o
  `BadSensorFailure`), y también los bits de límite (un valor fijado en su límite inferior o
  superior, o constante), así que un valor bueno que llega a su límite superior se archiva donde
  llegó. Los archivos CSV informan una calidad solo en una columna `quality` (formato largo); las
  series de las apps no informan ninguna: sus valores cuentan como buenos.
- **Modo**: de dónde viene el historial de sus señales (leído de la fuente, archivado aquí, o
  ambos), salvo que una señal defina el suyo.
- **Configuración de las señales de esta fuente**: retención, escaneo, desviación (% del rango) e
  intervalo máximo para todas las señales de la fuente. Los campos vacíos toman la configuración
  general; el valor propio de una señal prevalece sobre el de la fuente (vea Configuración).
- **Integración**: quién responde por la fuente y con qué frecuencia debe entregar datos. Los
  **Responsables** son personas o grupos de PlantCraft (`user:ana, group:automation`);
  **Contacto** indica cómo contactar al equipo que administra la conexión; **Intervalo esperado**
  es con qué frecuencia debe llegar un valor nuevo en al menos una de sus señales (vacío: sin
  vigilancia). Cuando la fuente se desconecta, o no envía nada durante más tiempo del esperado
  (*Fuente atrasada*), PlantCraft avisa a los responsables en Mensajes y por correo electrónico,
  con el contacto, y cierra el mensaje cuando la fuente vuelve. La página de la fuente lista sus
  responsables y el **historial** de sus estados (conectada, desconectada), conservado 90 días.
- **Probar** pide al colector que se conecte una vez e informe la respuesta del servidor.
- **Archivos CSV**: un archivo, o un patrón en la última parte de la ruta (`/csv/lab/*.csv`), que
  otra aplicación sigue escribiendo. El colector lo revisa cada **Revisar cada (minutos)**
  (predeterminado 5), archiva las líneas posteriores al último valor archivado y los archivos
  nuevos, y nunca los mueve ni los cambia. Sus señales existen solo en el archivo histórico. Los
  formatos y las reglas de hora son los de Importaciones; un archivo que se carga una sola vez va
  en **Importaciones**. Los archivos leídos como usted los verificó (columnas, formato de hora),
  con cada tag convertido en una señal, son una importación que **se repite desde una carpeta**:
  también aparece aquí, marcada **Se repite**.
- Una app fusionada en otra (Twin, CPMCraft y DataCraft en Analytics) muestra "App retirada": ya
  nada escribe sus series, y un administrador puede eliminarla con sus señales.
- **Suscribirse a los cambios** (OPC UA, desactivado de forma predeterminada): el servidor
  informa cada cambio, muestreado en el período de escaneo de la señal, en lugar de que Historian
  lea en cada escaneo. Un valor que se mantiene se vuelve a tomar en cada período de escaneo, así
  que la compresión funciona igual que con un escaneo. Un nodo que el servidor no quiere
  monitorear se lee en cada escaneo. Historian solo monitorea valores; no cambia nada en el
  servidor.
- **Explorar** lista las variables del servidor con sus unidades y rangos, para que pueda agregar
  muchas señales de una vez. Las señales ya archivadas aparecen marcadas. Deje vacíos el escaneo
  y la desviación para usar la configuración de la fuente o la general; una variable para la que
  el servidor no entrega rango se comprime entonces a esa fracción de su valor en lugar de su
  rango.
- **MQTT, Modbus y SQL** los lee el gateway (Telegraf), que envía cada valor al colector; sus
  señales existen solo en el archivo histórico. MQTT: el broker, los tópicos (`+` un nivel, `#`
  el resto) y si un mensaje es un número o JSON. Modbus TCP: el dispositivo, su slave id y cada
  registro o coil que se va a leer (tipo, dirección desde 0, tipo de dato, orden de bytes,
  escala; un valor de 64 bits indica los ocho bytes, de ABCDEFGH a GHEFCDAB). SQL: la base de
  datos, su cadena de conexión con `{password}` donde va la contraseña, y un SELECT ejecutado en
  cada período de escaneo (10 s si está vacío) por un usuario que solo puede leer. La columna de
  hora y las columnas de tag no son señales propias. Solo se archivan las filas más recientes
  que el último valor de una señal. **Explorar** lista lo que ha enviado el gateway; una fuente
  en silencio durante 60 s aparece como Desconectado.
  Almacenamiento y reenvío: los valores que el gateway lee mientras el colector no está disponible esperan en su búfer de disco y llegan en
  orden cuando el colector vuelve, también después de un reinicio del gateway; un lote enviado
  dos veces se toma una sola vez. El estado de la suite activa una advertencia cuando esperan más
  de 64 MB.
- **Sparkplug B** lo lee el colector, que se suscribe al broker (`tcp://` o `ssl://`) como un
  host que solo escucha: births, datos y deaths de un grupo, o de todos cuando el grupo está
  vacío. Nunca publica, así que no es un host primario y nunca pide a un nodo que vuelva a nacer.
  Con *Agregar señales desde los births* activado, cada métrica que describe un birth se vuelve
  una señal por sí sola (tag `<group>.<node>.<device>.<metric>`, con su tipo y unidad); si no,
  **Explorar** las lista para agregarlas. Un death marca como malos los valores del nodo o del
  dispositivo. Un nodo que nació antes de que Historian se conectara envía datos por alias que
  ningún birth nombró: su estado los cuenta, y se leen a partir del próximo birth del nodo
  (reinícielo para tenerlos ahora).
- **Resultados de laboratorio (LIMS)**: una fuente SQL marcada así escribe cada fila como un
  resultado de laboratorio en su hora de muestreo, con su estado (incierto hasta que se aprueba,
  malo cuando se rechaza) y las horas en que llegó al laboratorio y en que se aprobó. Una fila
  leída de nuevo sin cambios no se vuelve a escribir.
