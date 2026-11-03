# Conceptos

Las palabras que comparten PlantCraft y las apps de la suite.

### Fuente

Un sistema del que vienen los datos de la planta: un servidor OPC UA con acceso
al histórico, un PI Web API o un archivo CSV. El archivo del escenario nombra una;
los administradores agregan otras en la app **Historian**. Las contraseñas se
cifran en el servidor.

### Señal

Un tag de una fuente (un NodeId en OPC UA, un punto en PI, una columna en CSV) con
un nombre y una unidad de ingeniería. Una señal **en uso** es una que la suite
sigue y que las apps pueden leer.

### Activo

Una carpeta de la planta: sitio, unidad, área, equipo, lazo o un tipo propio.
Los activos forman un árbol, y cada uno puede tener señales vinculadas.

### Rol

Para qué sirve una señal en su activo: `pv`, `sp`, `op`, `mode` y `secondary`
para un lazo, o cualquier palabra (`pressure`, `vibration`...) para otros activos.

### Lazo

Un activo de tipo `loop` cuyas señales tienen roles de lazo. PlantCraft guarda el
lazo y sus señales; una app como Analytics decide cómo analizarlo.

### Grupo

Personas que trabajan juntas: un departamento, área, disciplina o equipo. Los
grupos forman un árbol; una persona puede estar en varios, y el coordinador de un
grupo lo dirige y ve las acciones de los grupos de abajo. Una acción puede ir a un
grupo, y cada grupo tiene su propia conversación.

### Origen

De dónde vino un activo: el archivo del **escenario**, un **mapa** de la planta o
una persona (**manual**). Una sincronización nunca cambia ni elimina lo que hizo
una persona.

### App

Un programa de la suite instalado al lado de PlantCraft (`PLANTCRAFT_APPS`).
Cada persona puede abrir todas las apps o solo algunas.

### Nivel de acceso

Administrador, ingeniería, lectura o solo dashboards: lo que una persona puede
cambiar, aquí y en las apps.

### Token y clave de app

Un token le demuestra a una app quién es usted; dura minutos y se renueva solo
mientras PlantCraft está abierto. Una clave de app permite que una app trabaje por
su cuenta; se muestra una sola vez y se puede revocar.

### Registro de auditoría

El registro de quién cambió qué, escrito por PlantCraft y por las apps.
