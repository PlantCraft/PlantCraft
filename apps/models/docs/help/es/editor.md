# Escribir código Modelica

**Código**, en la página de un modelo, abre su texto Modelica, y **Nueva biblioteca de bloques**,
en la página Bloques, abre el de una biblioteca. La pestaña **Texto** es un editor de Modelica:

- **Resaltado** de palabras clave, tipos, números, cadenas y comentarios.
- **Autocompletado**: empiece a escribir un nombre de clase (`Modelica.Blocks.`) y presione
  **Ctrl+Space** para ver las clases de la Modelica Standard Library y del paquete del modelo.
- **Mensajes en las líneas**: después de **Verificar**, cada error y advertencia que informa
  OpenModelica queda marcado en su línea; pase el cursor por encima para leerlo. El panel
  **Mensajes**, debajo del editor, los lista todos; haga clic en uno para ir a su línea.
- **Ctrl+S** (o **Guardar**) guarda el archivo. Un archivo también se guarda antes de una
  verificación, una simulación, una exportación o un diagrama, para que siempre usen lo que usted
  ve. Si otra persona guardó el mismo archivo mientras tanto, el guardado se rechaza en lugar de
  sobrescribir su trabajo: copie su cambio, recargue y vuelva a aplicarlo.
- **Ctrl+F** busca, **Ctrl+Z** deshace.

## Archivos y clases

El paquete de un modelo contiene archivos Modelica de la forma en que los guarda cualquier
herramienta Modelica:

- `Name.mo` contiene una clase de nivel superior (un modelo, un bloque, un paquete...).
- Un paquete puede ser una carpeta: `Name/package.mo` declara el paquete, `Name/Model.mo` contiene
  cada clase dentro de él (empezando con `within Name;`), y `Name/package.order` lista las clases
  en el orden en que se muestran.

El árbol de la izquierda lista los archivos y, debajo de cada uno, las clases que declara. El ▷
verde junto a una clase que se puede simular (un modelo o bloque que no es `partial`) abre su
simulación. **Nueva clase** agrega una clase en su propio archivo y pregunta lo que pregunta
"New Modelica Class" de OpenModelica: el nombre, la especialización (model, block, connector,
record, function, package, type, class), una descripción, una clase base para extender, el paquete
donde ponerla (un paquete con su propia carpeta; la clase se agrega a su `package.order`) y si es
parcial. Un modelo o bloque también puede partir de una plantilla (abajo y en Diagramas).

Límites: 200 archivos y 8 MB de texto por paquete, 1 MB por archivo.

## Versiones anteriores

Cada guardado conserva la versión anterior del archivo; se conservan las últimas 50 por archivo.

## Lo que un modelo no puede usar

Models ejecuta OpenModelica en el servidor, por lo que un modelo no puede ejecutar código propio
allí:

- las funciones `external` (código C o Fortran) se rechazan, salvo que el administrador las
  permita;
- `Modelica.Utilities.System`, `Modelica.Utilities.Files` y `Modelica.Utilities.Internal`
  (comandos, archivos y el entorno del servidor) se rechazan, se nombren como se nombren.

Una verificación que encuentra alguno de estos indica en qué línea está, y no se ejecuta nada.
