# Exportación

La exportación saca el historial en archivos abiertos, para un consultor, un colega o su propio
análisis en cualquier herramienta. Un ZIP contiene las series y los metadatos de la planta.

## Elegir qué exportar

1. **Busque** activos y tags en un solo cuadro: por nombre, tag, descripción o ruta. **Tipo** lo
   restringe a tags o a uno o más tipos de activo (unidades, equipos, lazos y cualquier otro
   tipo del árbol de activos de PlantCraft); un tipo solo lista todos sus activos.
2. **Marque** lo que quiere y presione **Agregar**. Un tag entra como tal; un activo agrega todos
   los tags que tiene debajo, cada uno con el activo y el rol de los que vino.
3. Repita cuantas veces quiera. La lista de abajo contiene el paquete. Se ordena por cualquier
   columna, pagina las listas largas y tiene su propio **filtro**. Elimine un tag con su **×**, o
   marque varios (la casilla del encabezado marca la página; **Seleccionar todos** marca todos
   los tags que muestra el filtro) y presione **Eliminar seleccionadas**. **Limpiar** empieza de
   nuevo.

Los tags que un activo nombra pero que Historian no archiva aparecen como *no archivado* y se
listan en el manifiesto; nunca se descartan en silencio.

## Guardar una exportación

Dé un nombre a la selección y presione **Guardar exportación**. Las exportaciones guardadas se
listan a la izquierda; abra una y descárguela de nuevo. Un período relativo ("últimas 24 horas")
lee hasta el momento de la descarga, así que "Unidad 100, último día" entrega el día más reciente
cada vez. **Guardar** la cambia; **Guardar como nueva** conserva la anterior. Cualquiera que
exporte puede guardar; el autor o alguien de Ingeniería la cambia o la elimina.

## Período y resolución

Un período relativo (de las últimas 2 horas a los últimos 30 días) termina ahora; **Desde –
hasta** acepta cualquier ventana. **Tal como se registró** entrega todos los valores archivados
(hasta 7 días). Un paso de 1 minuto, 10 minutos, 1 hora o 1 día entrega un valor por paso en una
grilla fija (hasta 31 días), y **Cada paso conserva** indica cuál: la **media** (ponderada en el
tiempo), el **primer** o el **último** valor registrado en el paso, o el **más bajo** o el **más
alto**. Un paso sin valor registrado se omite (la media mantiene el último valor a lo largo de
él). Una señal de texto (un modo, un estado) conserva el último valor del paso para el más bajo y
el más alto. `manifest.json` indica el paso y el agregado. Un paquete contiene hasta 500 tags.

## Privacidad

**Reemplazar los tags y los nombres de los activos por alias** convierte cada tag en `S001`,
`S002`… y cada activo en `A001`…, y omite los nombres y las descripciones. **Descargar clave**
guarda la tabla que convierte los alias de nuevo: guárdela aparte; nunca viaja en el paquete.

## Contenido

| Archivo | Qué contiene |
|---|---|
| `series.csv` | La hora (UTC) y luego una columna por señal, con el nombre de su tag (`source:tag` cuando dos fuentes comparten el tag); las celdas vacías indican que no hay valor en esa hora |
| `signals.csv` | Cada señal: tag, nombre, unidad, límites, el activo y el rol que cumple |
| `assets.csv` | Los activos de los que vienen las señales, con sus señales por rol |
| `plant-map.json` | Los activos y las señales como un mapa de planta de PlantCraft |
| `manifest.json` | Período, selecciones, lo que no se pudo leer y un SHA-256 de cada archivo |

Para abrirlo en otro PlantCraft, importe `series.csv` en su Historian (Importaciones) y luego
importe `plant-map.json` en Administración > Configuración. Cada exportación queda en el registro
de auditoría de PlantCraft.
