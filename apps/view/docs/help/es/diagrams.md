# Proceso

Una **pantalla de proceso** dibuja la planta como la conocen sus operadores: los equipos de la
biblioteca de símbolos unidos por sus líneas, con los valores de la planta sobre ellos. Los colores
indican el estado de un vistazo, los tanques se llenan con su nivel, las bombas se iluminan cuando
están en marcha y las líneas se mueven mientras algo fluye. Los diagramas solo leen: nada en un
diagrama escribe en la planta.

## Páginas

Una pantalla de proceso contiene la planta: cada unidad o área en su propia página, con las
pestañas debajo del nombre. En el editor, **Agregar página** crea una; el nombre de la página, su
posición y **Quitar página** están junto a las pestañas. Un símbolo, un valor o un texto puede
abrir otra página (Un clic abre › Otra página), como un conector fuera de página.

Una pantalla dibujada para toda la planta se abre en su **Resumen de la planta** (Nivel 1): un
bloque por unidad con su cantidad de equipos y de lazos y las burbujas de salud de sus lazos; un
clic abre la página de la unidad, y **‹ Resumen de la planta** en cada página de unidad lleva de
vuelta.

## Observar un diagrama

- **En vivo** muestra los valores actuales, actualizados cada pocos segundos (la cadencia propia
  del diagrama).
- **Colores**: verde es normal, ámbar una advertencia, rojo una alarma (parpadea), gris sin datos.
  Gris también significa que un valor no ha cambiado en 15 minutos: un número viejo nunca se
  muestra como una planta sana.
- Un símbolo vinculado a un estado de alarma de Alarms recibe una marca en su esquina mientras una
  alarma está activa, según su prioridad más urgente (ISA-101): un cuadrado con 1 para crítica, un
  triángulo con 2 para alta, un rombo con 3 para media y un círculo con 4 para baja. La forma y el
  número se leen sin color.
- Apunte a un elemento para leer sus valores, su unidad y por qué uno no se puede leer. La lista
  debajo del diagrama nombra cada valor que no se puede leer.
- Un dibujo grande puede nombrar sus **partes** (Editar › Pantalla de proceso › Partes): pestañas
  sobre él, **Resumen** para todo el dibujo y una por parte, ampliada; la pestaña de la parte a la
  vista queda marcada, y la dirección la guarda (`?part=`).
- Un clic en un valor dibuja su tendencia en una ventana sobre el diagrama, con el período, el
  intervalo y la apariencia de cada línea como en Tendencias; **Abrir en Tendencias** continúa con
  ella allí.
- Un clic en un equipo abre su panel junto al diagrama: sus valores en el dibujo, sus señales (cada
  una a una tendencia de distancia), los dashboards que lo muestran y **Página del activo**. Un
  elemento que su editor enlazó a otro lugar abre ese destino: otro diagrama o un dashboard. Un
  diagrama que se abre así muestra **Volver** con el nombre del primero, que regresa a la página que
  usted dejó.
- **Pantalla completa** es la del propio navegador: solo el diagrama, en vivo, para una pantalla
  de sala de control, con la tendencia y el panel del activo abriéndose dentro de ella; Esc sale.
- El nivel de un recipiente llena la forma propia del recipiente, con la superficie del líquido
  dibujada como una línea.

## Compartir un diagrama

Los editores de la carpeta de un diagrama lo comparten con **Compartir**, como un dashboard: un
**enlace público** abre solo este diagrama, en solo lectura y sin iniciar sesión, para una
pantalla de pared o un colega sin cuenta.

- Copie el enlace cuando se crea: se muestra una sola vez. Abre durante 7 a 365 días (un
  administrador puede crear uno que abra hasta que se revoque), y deja de funcionar de inmediato
  cuando usted lo revoca o elimina el diagrama.
- El enlace muestra el diagrama en vivo, con su barra de tiempo para reproducir la ventana.
  Agregue `?screen=1` al enlace para un quiosco: solo el diagrama, en vivo, ocupando la pantalla.
- Los clics en un diagrama compartido no abren nada: sus enlaces llevan a páginas que requieren
  iniciar sesión.
- Los administradores revisan todos los enlaces de la instalación (dashboards, informes y
  diagramas) en **Dashboards › Enlaces públicos**.

## Un diagrama en un dashboard

Un dashboard puede mostrar un diagrama guardado en un panel: **Editar › Agregar panel ›
Diagrama**, luego elija el diagrama. El panel lo dibuja en vivo, escalado para caber, actualizado
con el dashboard; lee la ventana de **Tiempo** del dashboard (si no, la propia del panel) y un clic
abre la página del diagrama.

Quién ve el diagrama depende de su carpeta: un espectador que no puede ver esa carpeta, o un enlace
público al dashboard cuando el diagrama está en una carpeta reservada para algunas personas, ve
"no disponible" en su lugar, y lo mismo todos una vez que el diagrama se elimina. Los informes no
admiten paneles de diagrama.

Para pasar por varios diagramas en una pantalla de sala de control, ponga cada uno en su propia
página de un dashboard, defina en la **Configuración** del dashboard que muestre la página siguiente
cada cierto tiempo, y ábralo en pantalla completa o por su enlace público.

## Volver en el tiempo

La barra de tiempo lee toda la ventana de una vez, así que recorrerla no le pide nada nuevo a la
plataforma.

- Elija la **ventana** (de 15 minutos a 7 días) y arrastre el cursor: el diagrama muestra los
  valores de ese instante.
- **Reproducir** recorre la ventana de 1x a 600x; **La ventana termina** mueve la ventana a
  cualquier momento pasado.
- Los estados que publican otras apps (alarmas, salud de los lazos) se muestran solo en vivo; en la
  reproducción quedan grises.

## Dibujar un diagrama

Los editores dibujan diagramas: **Nuevo diagrama**, o **Editar** en un diagrama.

1. **Arrastre equipos** de la biblioteca de la izquierda al lienzo (o haga clic en uno para
   soltarlo en el centro). La búsqueda encuentra un símbolo por nombre o por lo que es: bomba,
   tanque, válvula, columna.
2. **Únalo**: arrastre desde un puerto (los círculos pequeños de un símbolo) hasta otro símbolo o
   uno de sus puertos. La línea se traza sola con codos en ángulo recto y sigue a los símbolos
   cuando se mueven.
3. **Vincúlelo**: haga clic en un símbolo y elija el **activo que dibuja** (P-101, TK-1). Su
   color, su nivel y su marcha se vinculan de inmediato a partir de los roles de señal del activo;
   cambie cualquiera de ellos en el panel. **Valor** agrega un número junto al símbolo
   seleccionado (primero su PV), con sus propios límites. Marque **Indicador analógico (ISA-101)**
   para dibujar una barra gris debajo de él: el rango normal como una banda más oscura (de la
   advertencia baja a la alta cuando no está definido), los límites como marcas LL, L, H y HH, el
   setpoint (primero el SP de su activo) como una marca hueca y el valor como un puntero. Solo el
   puntero toma color, y solo fuera de lo normal.
4. **Guardar**. No se guarda nada antes; Cancelar deja el diagrama como estaba.

O comience desde un borrador: **A partir de activos** dispone una unidad a partir de sus equipos,
lazos y relaciones (cada uno con sus vinculaciones), o **toda la planta**: un resumen y una página
por unidad, y **Borrador con el asistente** hace un borrador a partir de lo que usted describe
(cuando el uso del modelo de lenguaje *diagram-draft* está activado en Setup). Ambos reemplazan el
lienzo, Deshacer lo restaura, y una nota dice lo que quedó fuera. Mueva las cosas a donde las
quiera y luego guarde.

Un símbolo seleccionado tiene un control en cada esquina: arrastre uno para redimensionarlo (Shift
libera las proporciones). Una línea seleccionada tiene un control en cada tramo que se puede mover:
arrástrelo para mover ese tramo, y los codos se mantienen en ángulo recto; **Escuadrar el trazado de
nuevo** en su panel deshace los codos. **Versiones** (el reloj en la barra de herramientas) lista
los últimos 30 guardados y restaura uno en el lienzo; guarde para conservarlo.

Teclas: Ctrl+Z y Ctrl+Y deshacen y rehacen, Delete elimina, Ctrl+C, Ctrl+V y Ctrl+D copian,
las flechas desplazan (Shift para pasos más grandes), R gira, F voltea, Esc borra la selección.
Ctrl y la rueda acercan y alejan; Alt y arrastrar, o el botón central, desplazan la vista.

El **tipo** de una línea la dibuja como tubería de proceso (su color dice lo que circula por ella:
agua, vapor, gas, aceite...), una señal (discontinua) o un servicio auxiliar (punteada).
