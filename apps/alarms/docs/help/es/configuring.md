# Reglas

Una regla dice **dónde** se aplica, **cuándo** se activa, **qué genera**, adónde van sus alarmas
(**salidas**) y **por qué**. Cada regla se lee como una oración en su página y en la lista.

## Dónde

- **Activos** nombrados, todos los activos **bajo** una rama del mapa de la planta, o todos los
  activos de un **tipo**, los de hoy y los que se agreguen después.
- Los activos de un **monitor de Analytics** (aquellos en los que se ejecuta).
- **En cualquier lugar**: cualquier activo que nombren los eventos de la regla.
- **Nada**: una regla solo sobre valores o eventos nombrados, con una alarma.

**Una alarma por** activo (predeterminado), por monitor, o una para toda la regla.

## Cuándo: Simple o Python

- **Simple**: hasta tres condiciones unidas por **y** u **o**. Una condición lee un **valor**
  (por encima de, por debajo de, entre, fuera de, cambió, o **no cambió**: una medición
  congelada) con una **banda muerta**, o un **evento** (abierto durante al menos cierto tiempo, o
  contado cierta cantidad de veces en una ventana). Puede tener que cumplirse **durante al
  menos** cierta cantidad de minutos o valores, y la alarma se normaliza **después** de cierto
  tiempo de vuelta a normal.
- **Python**: para cualquier otra lógica. Elija algunos valores como entradas; `check(inputs)` lee
  la última lectura de cada una (`inputs.flow`, None cuando no hay datos) y responde
  `True, "sentence"` para activar o `False, ""` para no hacerlo. El editor empieza con un ejemplo
  comentado para las entradas, muestra lo que entra y sale junto al código, y se abre a pantalla
  completa con **Ampliar**. Solo los administradores escriben código; se ejecuta en el área
  aislada de PlantCraft (sin red, sin archivos, con tiempo y memoria limitados), como máximo una
  vez por minuto.

Una regla dibujada en el antiguo editor de Bloques se sigue ejecutando tal como se dibujó (las que
encajaban se reescribieron como Simple o Python); para cambiar su lógica, escríbala de nuevo en
Simple o Python.

Los valores y eventos se eligen en el **Explorer**: el mapa de la planta con las señales de cada
activo, las series que las apps calcularon sobre él y los eventos que lo nombraron. Un valor
elegido para **cada activo** se lee en todos los activos de la regla.

### Solo mientras: alarmas que dependen del estado de la planta

**Solo mientras…** en el formulario Simple agrega una condición permisiva: una condición de valor
que debe cumplirse para que la alarma se evalúe siquiera (alarmas basadas en estado, supresión
por diseño de ISA-18.2). Una alarma de flujo bajo **solo mientras P-101 en marcha ≥ 1**, con
**Habilitada después de** 30 s para que el flujo se estabilice después de un arranque. Mientras
la condición permisiva no se cumple, la alarma está suprimida por diseño: no se activa, se
normaliza si estaba activa, y su página lo indica. Una condición permisiva que no se puede
evaluar (sin datos) deja la alarma habilitada, así que una señal mala nunca oculta una alarma.
En Bloques es la entrada **Enabled when** de Raise an alarm.

### Límites por grado: un límite para cada producto

Una línea que produce varios grados a menudo necesita un límite distinto para cada uno. Una
alarma de índice de fluidez, por ejemplo, puede estar en 50 para el grado HD-5 y en 90 para el
LD-2.

1. En el formulario Simple, elija **Límites por grado…**.
2. Indique de dónde viene el grado que se está produciendo:
   - **Una señal** que contiene el código del grado. El código 3 es el grado "3".
   - **Un evento**: el evento más reciente de los tipos que elija nombra el grado, en un campo del
     payload (`grade` de forma predeterminada). El `mes.grade.changed` de un MES es un ejemplo.
3. En cada condición comparada con un límite, liste los grados con sus límites.

El límite de arriba sigue valiendo en dos casos: antes de que se conozca algún grado, y para un
grado que la lista no nombra. La página de la alarma indica qué grado y qué límite se aplican.
Alarms conserva el último grado entre evaluaciones, así que un evento de cambio de grado se
necesita una sola vez.

En Bloques es un bloque **Grade limit** conectado a la entrada **Limit** de un Compare.

## Qué genera

- **Una alarma**: necesita un reconocimiento, se muestra en Alarms y cuenta en Desempeño
  (ISA-18.2).
- **Una alerta**: se muestra en Alarms y se envía, pero no necesita reconocimiento y queda fuera
  de Desempeño. Sirve para lo que las apps informan sobre sí mismas, como una ejecución fallida.

La **prioridad** es crítica, alta, media o baja; mantenga la mayoría de las reglas en baja.
**Responsable**, **área** y **disciplina** indican quién responde por ella y dónde está; el área
viene del árbol de activos cuando se deja vacía. La **racionalización** es la causa, la
consecuencia de no actuar y la acción correctiva: una alarma sin una acción para el operador no
debería ser una alarma.

## Salidas

- **Alarms**: siempre; la alarma se lista para reconocer, suprimir y comentar.
- **Dashboards** (activado): sus alarmas colorean sus activos y aparecen en los widgets de
  alarmas activas de View y del Resumen.
- **Mensajes** (activado, al responsable): en Mensajes de PlantCraft, agrupados, con
  recordatorios, horarios y escalamiento. Vea **Notificaciones**.
- **Correo electrónico**: aparece una vez que un administrador configuró el servidor de correo de
  PlantCraft (Configuración, Correo electrónico); se envía a las personas que lo permiten en su
  perfil.

## Probar antes de guardar

**Probar** ejecuta la regla, tal como está escrita, sobre los últimos días de valores y eventos e
indica cuántas alarmas habría generado, sobre cuántos objetivos, y aproximadamente cuántos
mensajes habría enviado una vez agrupados. Si una regla se activaría decenas de veces al día en
operación normal, hay que trabajar en su límite, banda muerta, retardo o conteo.

## Desactivar una regla

**Desactivar** en la página de la regla la detiene: sus alarmas quedan fuera de servicio hasta
que se active. Eliminar una regla termina sus alarmas; su bitácora se conserva. Cambiar la lógica
de una regla termina sus alarmas activas y vuelve a evaluar a partir de entonces.

## Importar la lista de alarmas del DCS

**Importar lista de alarmas** en Reglas lee la lista de alarmas exportada del DCS (la base de
datos maestra de alarmas): un archivo CSV, o Excel guardado como .xlsx. **Plantilla** entrega un
archivo con las columnas que lee Alarms. Cada fila es una alarma sobre una señal:

- **tag** (la señal, por su id o su nombre en el DCS, como `FIC-1001.PV`) y **type**: HH, HI, LO
  o LL (también se leen PVHI, HIHI, LOLO y similares);
- **limit** y, de forma opcional, unidad, **priority** (critical, high, medium, low, o de 1, la
  más urgente, a 4), banda muerta, retardo a la activación (segundos, `2 min` o `00:00:10`),
  descripción, causa, consecuencia, acción y habilitada.

Leer el archivo no cambia nada. La revisión lista lo que haría una aplicación: reglas **nuevas**,
**cambiadas** (campo por campo, antes y después), **eliminadas** (alarmas que generó una
importación anterior y que la lista ya no tiene) y las filas que no se pudieron leer, con su
línea. Desmarque lo que no debe cambiar y presione **Aplicar**. La regla de una alarma eliminada
se desactiva, nunca se elimina. Lo que las personas definieron en el propio Alarms (dónde, a
quién se notifica, responsable, área) se conserva. Una regla que alguien cambió después de que se
leyó el archivo se deja como está y se lista: lea el archivo de nuevo para verla. Las reglas
escritas a mano nunca se tocan. Cada importación se compara alarma por alarma por su tag y su
tipo.
