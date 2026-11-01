# Paneles

| Tipo | Muestra | Señales |
|---|---|---|
| Valor | Un valor (último, media, mín., máx., ...) por señal sobre una ventana, coloreado según sus umbrales, con su línea debajo si se desea | hasta 24 |
| Indicador | Un valor en un medidor (o un indicador de barra), con las bandas de umbral; un medidor por señal. Estilo **Indicador analógico (ISA-101)**: una barra gris con el rango normal, los límites LL, L, H y HH de los umbrales y el setpoint (una señal de rol SP del mismo activo); el puntero toma color solo fuera de lo normal | hasta 24 |
| Tendencia | Líneas sobre una ventana; dos unidades tienen dos ejes; umbrales como líneas o áreas | hasta 24 |
| Gráfico de barras | Un valor por señal, vertical u horizontal, coloreado según los umbrales | hasta 24 |
| Tabla | Último, media, mín. y máx. por señal, celdas coloreadas según los umbrales | hasta 24 |
| Dispersión (X-Y) | Una señal frente a otra, sobre la misma cuadrícula de tiempo: la primera es x, la segunda y (PV frente a OP muestra una válvula con fricción estática) | 2 |
| Texto | Una nota: para qué sirve el dashboard, qué vigilar, a quién llamar | ninguna |
| Controlador multivariable | Un APC de terceros, solo lectura: cada variable manipulada (MV) y controlada (CV) con su valor, límites bajo y alto, objetivo de estado estacionario, estado y precio sombra actuales, una barra de su rango (el valor como puntero, el objetivo como marca hueca) y su valor y objetivo a lo largo del intervalo de tiempo (el horizonte). Una variable cuyo objetivo (si no, su valor) está dentro de su banda de un límite se marca **En el límite alto** o **En el límite bajo** | ninguna: el controlador |

El controlador es un activo del tipo `apc` (roles `on`, `mode`; atributos `vendor`, `cost_unit`)
con activos del tipo `apc_mv` y `apc_cv` debajo (roles `value`, `lo`, `hi`, `target`, `status`,
`shadow_price`; atributo `limit_band`, 1 % de alto menos bajo cuando está vacío). Analytics lee los
mismos nombres. View nunca escribe en el controlador.

Los paneles guardados antes de la ronda 7 se abren como antes: un panel de KPI o de "valor y
línea" ahora es un Valor (el segundo con su línea activada), y sus límites ahora son umbrales.

## El editor de paneles

**Agregar panel** abre el editor en pantalla completa. Primero elija el **tipo de panel**; la
vista previa ocupa la izquierda y las opciones se agrupan a la derecha, con un cuadro de búsqueda
que deja solo las opciones cuyo nombre coincide. **Visualización**, arriba, cambia el tipo después:
las señales, los umbrales, las correspondencias y las excepciones se mantienen. **Aplicar** pone el
panel en el dashboard (el dashboard se guarda con **Guardar**), **Descartar** lo deja como estaba.

**Señales.** Cada línea de un panel es una de estas:

- **Señal**: una señal de PlantCraft, por nombre o descripción.
- **Activo**: un activo y un rol de señal, o **todas las señales del activo**; los botones de rol
  debajo dejan solo algunos roles (PV, SP, OP, ...).
- **Variable**: el activo elegido en una variable del dashboard (`${loop}`), con un rol o todos los
  roles. El panel sigue al selector; vea [Dashboards](dashboards.md#variables).

Un panel tiene hasta 12 líneas, que representan como máximo 24 señales (una nota indica cuando se
recortaron más). Un nuevo panel de tendencia, de barras o de tabla comienza con todas las señales
del activo; uno de valor o de indicador, con una.

## Opciones

| Grupo | Qué define |
|---|---|
| Panel | Título, descripción, página, ventana de tiempo propia |
| Valor, Indicador, Gráfico de barras, Tabla, Gráfico, Dispersión | Lo que dibuja el tipo: el valor (último, media, ...), la línea bajo un valor, el medidor o el indicador de barra, la dirección de las barras, el estilo de línea y los puntos, las columnas de la tabla |
| Leyenda, Eje | Posición y tabla de la leyenda (con último, media, mín., máx.), etiquetas de los ejes, escala, mín. y máx. flexibles |
| Opciones estándar | Unidad, decimales, mín. y máx., el rango normal (la línea de un valor y el indicador analógico lo sombrean; vacío: entre el escalón normal de los umbrales y el siguiente), color de los valores |
| Umbrales | Escalones a partir de un color base: cada escalón tiene un valor y un color; **absolutos** o **porcentaje** de mín. a máx.; en tendencias y barras se muestran como líneas, áreas, ambas o nada, con sus etiquetas |
| Correspondencias de valores | Un valor o un rango mostrado como una palabra y un color (0 como "Detenido", 1 como "En marcha") |
| Excepciones | Otras opciones solo para algunas líneas, elegidas por rol, señal o nombre (el SP discontinuo, la OP en el eje derecho) |
| Diseño | Ancho y alto en celdas de la cuadrícula |
| Opciones de repetición | Repetir el panel para cada valor de una variable, lado a lado o uno debajo de otro |

Los colores siguen siendo legibles en los temas claro y oscuro: un color demasiado cercano al
fondo se oscurece o se aclara hasta que se lee, y el texto sobre una celda rellena es blanco o
negro, el que se lea mejor.

## Tamaño y posición

La cuadrícula tiene 12 columnas; una fila mide unos 90 píxeles. En **Editar**, arrastre un panel
por su barra de título y redimensiónelo desde su esquina inferior derecha; los demás paneles se
apartan. **Duplicar** pone una copia debajo. Los paneles con un gráfico, un medidor o una tabla
ocupan al menos 2 filas. En pantallas más angostas los paneles ocupan la mitad del ancho o todo, y
en un teléfono cada panel ocupa todo el ancho con su propia altura.

**Pantalla completa.** Los paneles de tendencia, de barras y de dispersión tienen un botón de
pantalla completa en su esquina: el panel ocupa la ventana, con acercar, desplazar, restablecer y
descarga de la imagen. Esc lo cierra. La página Tendencias tiene su propio botón **Pantalla
completa** encima del gráfico.

**Resultados de otras apps.** Los paneles de valor, de barras y de tabla también pueden mostrar lo
que otra app instalada publicó sobre un activo o una señal, como la salud de los lazos o la calidad
de la señal de Analytics: elija el activo y luego el resultado en "Muestra". El color es el estado
propio de la app (OK, Advertencia, Crítico), no los umbrales del panel; el valor es su puntuación
sobre 100. Un resultado que su app no actualizó a tiempo se muestra como desactualizado y
desconocido. En un panel de tendencia la misma elección dibuja el historial del resultado, cuando
su app lo archiva (Analytics conserva la salud de cada lazo en el tiempo).

**Las ventanas** van de segundos a 366 días. Una tendencia dibuja como máximo unos 600 puntos por
línea, cada uno la media de su paso. Cuando una ventana no tiene muestras, una tendencia muestra
los datos más recientes que encuentra y lo indica debajo del gráfico.
