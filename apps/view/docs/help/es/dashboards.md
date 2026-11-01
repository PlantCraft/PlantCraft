# Dashboards

Un dashboard es una pantalla de paneles sobre las señales y los activos de la planta, leídos de
PlantCraft. Los dashboards están en carpetas; una carpeta dice quién ve y quién edita sus
dashboards.

- **Nuevo dashboard** pide un nombre, una carpeta y el punto de partida: una cuadrícula vacía, una
  plantilla construida a partir de los activos de la planta (un detalle de lazo, un resumen de
  unidad) o un archivo exportado desde View. El editor se abre con él; no se guarda nada hasta que
  presione **Guardar** (Cancelar no deja rastro).
- **Editar** abre el dashboard para hacer cambios: agregue, modifique, arrastre, redimensione y
  quite paneles, luego **Guardar**. Si otra persona lo guardó mientras tanto, Dashboards pregunta
  antes de reemplazar su versión.
- **Actualizar** lee los paneles de nuevo cada 15 s a 5 min, o solo cuando usted lo pide.
- **Pantalla completa** oculta todo menos los paneles, para una pared de sala de control.
- **Tiempo** define una ventana para todos los paneles (o cada panel mantiene la suya). La
  dirección en el navegador guarda la página, las variables (`?var-loop=fic-101`), la ventana y la
  pantalla completa, así un marcador abre la misma vista.

## Variables

Las variables son los selectores en la parte superior de un dashboard (Configuración › Variables),
como en Grafana. Así un dashboard sirve para todos los activos de un tipo:

| Tipo | Ofrece |
|---|---|
| Activo | Los activos de un tipo (cada lazo, cada bomba); bajo una variable **padre**, solo los activos bajo los elegidos allí |
| Personalizada | Una lista que usted escribe (`PV, SP, OP` o `north, south`) |
| Intervalo | Ventanas de tiempo (`1h, 8h, 24h`), para paneles que usan `${period}` como su ventana |

Una variable puede tomar **varios valores** y ofrecer **Todos**. Los paneles la usan como `${name}`
en una línea de señal (modo Variable, o dentro del nombre de una señal: `FIC-${unit}.PV`), un
título, una nota o una ventana. Un panel con **Repetir** se dibuja una vez por cada valor elegido,
lado a lado o uno debajo de otro; mientras se edita se muestra una vez. Un selector sin opciones lo
indica en lugar de mostrar paneles vacíos. Los dashboards creados con el antiguo selector de
**Activo** se abren con él como su primera variable.

## Páginas

Un dashboard puede tener hasta 10 páginas, mostradas como pestañas en la parte superior (un
dashboard con una página no muestra pestañas). Mientras se edita, **Agregar página** agrega una;
el nombre de la página, las flechas y la papelera junto a ella renombran, mueven y quitan la
página mostrada (quitar una página quita sus paneles). La **Página** de un panel, en el editor de
paneles, lo mueve a otra página. El activo, la ventana de tiempo y la actualización son del
dashboard: se mantienen al cambiar de página. Solo la página mostrada lee datos.

**Pasar páginas en pantalla completa** (Configuración › Tiempo, con dos páginas o más) muestra la
página siguiente cada 30 s, 1 min o 5 min en pantalla completa y en los enlaces públicos: una
pantalla de sala de control recorre todas las páginas.

## Carpetas

La lista muestra los dashboards por carpeta; **General** contiene los que están fuera de toda
carpeta, y todas las personas con acceso a View los ven. **Nueva carpeta** (editores) nombra una
carpeta y quién puede usarla:

- **Quién ve sus dashboards**: todas las personas con acceso a View, o solo algunas personas y
  grupos de la plataforma (Configuración › Personas › Grupos en PlantCraft). Los demás no ven la
  carpeta ni sus dashboards en ningún lugar: ni en la lista, ni en las páginas de activos, ni en
  los widgets del Resumen, ni en la API.
- **Quién edita sus dashboards**: todos los editores de View, o solo algunas personas y grupos.
  Solo los editores de View entre ellos modifican, comparten, agregan o eliminan sus dashboards;
  ellos siempre ven la carpeta.

Los administradores ven y modifican todas las carpetas. Una carpeta se elimina una vez que está
vacía. Un enlace público sigue mostrando su dashboard a quien lo tenga, sea cual sea la carpeta.

## Compartir, Configuración, Editar

Junto al selector de tiempo: **Compartir** (enlaces públicos), **Configuración** y **Editar**.
Configuración guarda de inmediato, sin entrar al editor; dentro del editor cambia lo que guarda
**Guardar**.

| Sección | Qué contiene |
|---|---|
| General | Nombre, carpeta, descripción, etiquetas (la búsqueda de la lista las encuentra) |
| Tiempo | La ventana con la que abre, la actualización, el paso de páginas en pantalla completa |
| Visualización | **Cursor compartido**: al pasar el cursor sobre una tendencia se marca el mismo momento en las demás. **Quiosco**: la pantalla completa y los enlaces públicos muestran solo los paneles (Esc sale) |
| Variables | Los selectores de arriba: variables de activo, personalizadas y de intervalo, sus valores predeterminados, varios valores, Todos, un padre |
| Versiones | Los últimos 30 guardados, quién y cuándo; **Restaurar** guarda de nuevo una antigua como la más reciente |
| JSON | El dashboard como archivo, para comenzar un dashboard a partir de él en otro lugar |

Un dashboard guardado lee los datos de la planta con la clave de la app View, así que todos los
espectadores ven los mismos números, y una lectura se comparte entre todos los espectadores
durante unos segundos.
