# Documents

Documents reúne los documentos de la planta en un solo lugar: manuales de operación, narrativas de
control, P&ID, hojas de datos, procedimientos, guías de solución de problemas, registros de
mantenimiento e informes de incidentes. Lee cada archivo, para que usted y el asistente encuentren
el pasaje que responde a una pregunta, con su página.

## Resumen

Documents abre en su **Resumen**: un cuadro de búsqueda (palabras o una pregunta; abre **Buscar**
con lo que escribió), cuántos documentos están listos para la búsqueda y cuántos están en lectura,
los documentos más recientes (con cuándo se envió o modificó cada uno) y los que nadie ha vinculado
todavía a los activos de la planta. Mientras se leen archivos, una línea encima de los widgets
indica cuántos. **Personalizar** organiza los widgets; **Biblioteca**, en el menú, abre las
carpetas y todos los documentos.

## Enviar un documento

En la **Biblioteca**, elija una carpeta en la columna de la izquierda y seleccione **Enviar
archivos** (o suelte archivos en la página). La línea debajo del título indica lo que se lee: PDF,
Word (.docx), Excel (.xlsx), PowerPoint (.pptx), texto, Markdown, CSV y HTML, hasta 200 MB por
archivo. Los archivos .doc, .xls y .ppt antiguos no se leen: guárdelos primero en el formato nuevo.

- Asigne al documento su **número** (DOC-U200-OM-001), **título**, una **descripción** (qué
  cubre, para quién; la búsqueda y el asistente también la leen), **tipo** y **unidad**. Un archivo
  enviado con un número que ya existe se convierte en su **nueva revisión**; la revisión anterior
  queda en el historial del documento y ya no se busca en ella.
- El archivo se lee en segundo plano, de unos segundos a unos minutos: la **Cola** de la barra
  lateral lista los archivos en espera, en lectura y leídos en el último día. Un archivo que no
  se puede leer indica por qué (por ejemplo, un PDF digitalizado sin texto).
- Los tags encontrados en el texto (FIC-1003, FV-1003, P-1003) que existen en el árbol de activos
  de PlantCraft se **sugieren** como activos del documento. Confírmelos en la página del documento:
  el asistente pone primero un documento vinculado a un activo cuando usted pregunta por ese
  activo.
- **Vínculos por verificar** (en la Biblioteca, si usted puede editar) lista los activos
  encontrados en el texto de todos los documentos que usted puede modificar. Elija varios y
  márquelos como **Correcto**, para vincularlos, o **Incorrecto**, para que no se vuelvan a
  sugerir. Un administrador puede definir un número de menciones a partir del cual un activo se
  vincula de inmediato (`DOCCRAFT_ASSET_AUTO_MENTIONS`, desactivado por defecto).

## Encontrar algo

**Buscar** encuentra pasajes por sus palabras y por su sentido, en inglés y en portugués: "¿por
qué salta el caudal de reciclo?" encuentra el pasaje sobre la fricción estática (stiction) de la
válvula aunque nunca diga "salta". Filtre por tipo o por activo. Cada resultado muestra la parte del
pasaje alrededor de sus palabras, con las palabras en negrita, y abre el documento en ese pasaje,
marcado, de nuevo con sus palabras en negrita. **Abrir el PDF**, en un PDF, abre en esa página;
**Abrir el documento**, en un archivo Word, lo muestra como página (su texto, títulos y tablas).
Ctrl+K, en cualquier lugar de la
suite, encuentra documentos por número o título y los mejores pasajes.

## P&ID

Los P&ID y el mapa de la planta están en **PlantCraft PID**, una app aparte que un administrador instala
con su licencia. Documents guarda los P&ID enviados como PDF como cualquier otro documento, leídos por su
texto; los dibujos enviados como SVG, DEXPI o escaneos van a PlantCraft PID.

## Preguntar al asistente

El asistente busca y lee los documentos que usted puede abrir, y cita cada dato como [n] con el
documento, la revisión y la página; cada [n] abre el documento en ese pasaje. Busca en los
documentos con cada pregunta, en todas las apps: en una página sobre un activo (un lazo en
Analytics, el tag de una alarma) también busca sobre ese activo. En la página de un documento puede
resumirlo o responder solo a partir de él; en
la página de un activo lista los documentos sobre él. Analytics y Alarms le piden que verifique los
documentos cuando buscan la causa de un problema.

## Carpetas y quién lee

Una carpeta indica quién la **ve** y quién la **modifica** (personas y grupos); vacío significa
todas las personas con acceso a Documents. Un documento en una carpeta que usted no puede ver no
existe para usted: no aparece en listas, búsqueda, el asistente ni enlaces. Desmarque **El
asistente puede leerlo** en una carpeta o un documento para mantenerlo fuera del alcance del
asistente mientras las personas lo siguen encontrando.

Cada documento enviado, modificado, descargado o eliminado, y cada búsqueda que hace el asistente,
queda registrado en el registro de auditoría de PlantCraft.
