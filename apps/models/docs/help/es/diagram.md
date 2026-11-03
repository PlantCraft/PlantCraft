# Dibujar diagramas

La pestaña **Diagrama** dibuja la clase seleccionada: cada componente se dibuja con el ícono de su
biblioteca en la posición que indica su anotación `Placement`, y cada ecuación `connect` con su
línea.

Cada cambio hecho en el diagrama se escribe en el texto de la clase, como usted mismo lo
escribiría, y el diagrama se vuelve a dibujar a partir del texto. El texto sigue siendo la única
fuente: lo que usted dibuja es lo que puede leer, comparar y guardar en el control de versiones.

| Para | Haga |
|---|---|
| Agregar un componente | Abra **Biblioteca** a la izquierda, busque la clase (con la búsqueda o abriendo los paquetes) y arrástrela al diagrama; o arrastre un modelo o bloque del árbol **Archivos** |
| Mover un componente | Arrástrelo |
| Girarlo un cuarto de vuelta | Selecciónelo y presione **R** (o el botón de girar) |
| Eliminar un componente | Selecciónelo y presione **Delete**; sus conexiones se eliminan con él |
| Conectar dos conectores | Arrastre de un conector al otro (el cursor se vuelve una cruz sobre un conector) |
| Eliminar una conexión | Haga clic en su línea y presione **Delete** |
| Cambiar un parámetro | Seleccione el componente; sus parámetros están a la derecha. Escriba un valor y presione **Aplicar**; un valor vacío quita el suyo y vuelve a aplicarse el predeterminado |
| Zoom, desplazamiento | Rueda del mouse; arrastre el fondo vacío |

Un componente nuevo recibe un nombre a partir de su clase (`gain`, `gain1`...). Para renombrarlo,
cámbielo en el texto, junto con sus conexiones.

Los conectores solo se conectan cuando son compatibles (un `RealOutput` con un `RealInput`, un
puerto de fluido con un puerto de fluido...). El diagrama escribe el `connect`; **Verificar** indica
si los dos no encajan.

Los componentes heredados (de un `extends`) se dibujan pero no se mueven: cámbielos en la clase
base.

## Una planta con sus propios componentes

Construya las piezas una vez y luego conéctelas, como en OpenModelica:

1. **Nueva clase**, partiendo de un componente: un **bloque de señal** (entrada `u`, salida `y`),
   un **componente térmico** (un puerto de calor) o un **componente eléctrico** (dos pines). Cada
   uno viene con sus conectores, parámetros, una ecuación para modificar y un ícono.
2. **Nueva clase**, partiendo de un **Sistema**: un diagrama vacío con un `experiment`. Un diagrama
   vacío lo indica, con un botón que abre la **Biblioteca**.
3. Abra el **Diagrama** del sistema y arrastre sus componentes desde el árbol **Archivos** (y
   fuentes, sensores o controladores desde la **Biblioteca**). Conéctelos y **Simule** el sistema:
   todos los componentes se ejecutan juntos.

Un componente que se modifica después cambia todos los sistemas que lo usan. Una clase no se puede
soltar dentro de sí misma.

## La biblioteca

**Biblioteca** lista la Modelica Standard Library 4.0.0. Haga clic en una clase para leer su ícono,
parámetros, documentación y texto; arrástrela a un diagrama para usarla. Los paquetes de
documentación y las clases internas no se listan.

## Documentación

La pestaña **Documentación** muestra la anotación `Documentation(info = "<html>...</html>")` de la
clase. Se muestra sin ningún script y sin enlaces fuera de la página.
