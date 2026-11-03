# Algoritmos

Un algoritmo es un diagrama de bloques: las señales entran por la izquierda, pasan por
verificaciones de calidad de datos, transformaciones y métodos, se combinan y salen como salidas
por la derecha. Cada conexión une dos puertos del mismo tipo, y el algoritmo se verifica antes de
ejecutarse o guardarse: un bloque con una entrada sin conectar, una conexión entre puertos que no
coinciden o un ciclo en las conexiones se marca en el bloque, en palabras.

PlantCraft incluye seis algoritmos, de solo lectura, con **PlantCraft** como autor:

- **Lazo de flujo**: el valor por defecto de los lazos de flujo y de los lazos de tipo
  desconocido. El error PV–SP, la saturación de la salida y la calidad del muestreo forman la
  salud (0 a 100); el recorrido de la válvula y la fricción estática se juzgan con ellos; la
  oscilación y el ruido se señalan junto a ella; el modo manual, los movimientos de setpoint y las
  intervenciones son contexto.
- **Lazo de nivel**: el valor por defecto de los lazos de nivel, para niveles mantenidos ajustados
  en su setpoint: el error, la salida y el recorrido de la válvula forman la salud; la oscilación y
  la fricción estática se señalan junto a ella.
- **Nivel pulmón**: para niveles que deben absorber las perturbaciones dentro de una banda.
- **Lazo de temperatura o de presión**: el valor por defecto de los lazos de temperatura, presión
  y composición: lazos lentos juzgados por el índice de Harris (varianza frente al control de
  varianza mínima) junto al error y la salida.
- **Calidad de las señales**: las verificaciones de calidad de datos sobre cada señal, en su propio
  monitor.
- **Gemelo de la unidad**: un modelo de proceso se ejecuta junto a una unidad con sus propias
  señales, y la diferencia entre lo que predice y lo que mide la planta se juzga frente a la
  operación normal. Se ejecuta sobre activos.

En la planta de demostración del Simulator, Analytics agrega sus gemelos (los hornos y los modelos
de proceso de dos lazos) por sí mismo la primera vez que encuentra la planta: calibrados sobre las
últimas horas y programados sobre sus activos, para que los modelos se ejecuten desde el inicio.
Un gemelo eliminado queda eliminado (**Agregar los ejemplos de modelos de la planta** lo trae de
vuelta). Las verificaciones de válvula y de oscilación son bloques de la biblioteca *Desempeño de
lazos de control*: arrástrelos a cualquier algoritmo.

Cada algoritmo tiene **etiquetas** (lazo de control, calidad de datos, gemelo digital, o las
suyas), un **responsable**, una **versión** (cada guardado agrega una) y, cuando se fija, un
**grupo responsable**: los miembros y los coordinadores del grupo lo editan, los demás lo leen. La
lista indica cuántos activos usan cada uno.

Para cambiar uno, use **Duplicar** y edite la copia; un lazo o un monitor usa entonces la copia.

## Dibujar un algoritmo

Abra un algoritmo y el editor se abre en su propia ventana. Arrastre bloques desde la paleta de la
izquierda (busque por nombre), conecte una salida a una entrada (las entradas compatibles se
iluminan) y fije los parámetros de un bloque en el panel de la derecha, donde se describe cada
puerto y cada parámetro.

- **Los colores de las conexiones** indican qué fluye: azul, una señal en el tiempo; violeta, el
  modo; ámbar, un número; verde, un resultado (ok, advertencia, malo o desconocido, con una
  puntuación de 0 a 100 y una frase); gris, una condición (partes de la ventana).
- **La verificación de datos del lazo** va después de las señales: transmite PV, SP, OP y modo
  cuando los datos son utilizables, y nada (con el motivo) cuando no lo son, para que los métodos
  posteriores no juzguen datos malos.
- **Las transformaciones** preparan las señales: aritmética (*Expresión* como `a * b / c`, *Unidad
  de ingeniería*), filtros (*Media móvil*, *Filtro pasa bajos*, *Derivada*, *Remuestrear*, *Quitar
  tendencia*, *Retardo*), *Seleccionar por condición* y *Solo en operación*, que conserva la
  operación estable y deja fuera los arranques y las paradas.
- **Las estadísticas** resumen una señal en la ventana, o solo donde se cumple una condición:
  *Media*, *Desviación estándar*, *Percentil*, *Histograma*, *Correlación* (con el mejor desfase),
  *Cambios en escalón* y *Tiempo fuera de límites*.
- **Equipos**: *UA del intercambiador de calor* (sigue el ensuciamiento frente al UA limpio) y
  *Eficiencia de la bomba* (frente a la curva del fabricante).
- **Las condiciones** (conexiones grises) marcan partes de la ventana: *Comparar con un límite*
  (un flujo de alimentación por encima de su mínimo: la unidad opera) y *AND / OR / NOT* para
  combinarlas.
- **Lógica**: *Peor de* conserva el peor resultado; *Promedio* puntúa la media frente a dos
  límites; *Regla* reemplaza un resultado cuando una prueba es mala ("si los datos de la PV son
  malos, el resultado de la válvula no es confiable"); *Límites* convierte un número en un
  resultado.
- **Salidas**: *Salud del lazo* (la salud del lazo y sus hallazgos), *Resultado en el activo* (un
  resultado con nombre que leen todas las apps), *Mensaje* (un evento cuando su entrada se vuelve
  mala, que se cierra cuando se recupera). Cualquier número, resultado o serie también se puede
  **registrar en Historian** con el interruptor de su puerto: Tendencias, Dashboards y el asistente
  la leen entonces. Sobre activos, cada monitor indica en sus **Salidas registradas** cuáles de
  ellas conserva y por cuánto tiempo (un resultado para siempre, otros valores 400 días, una serie
  sus últimas 10 ejecuciones, por defecto), con lo que eso cuesta; el Historian muestra las
  ejecuciones de una serie una sobre otra.

**Probar** ejecuta el diagrama sobre los datos recientes de un lazo sin guardar nada y muestra en
cada conexión lo que llevó. Después de guardar, **Monitor** lo ejecuta cada N minutos sobre
todos los lazos o sobre los elegidos; cada ejecución aparece en **Resultados > Historial de
ejecuciones**. El panel junto al diagrama indica **dónde se usa**: los lazos que usan el algoritmo
y sus monitores.

Cada algoritmo tiene su documentación en las mismas cinco partes (para qué sirve, los activos que
lee, cuándo usarlo, cómo leer su resultado, instrucciones para el asistente). Lo que queda vacío
se escribe a partir del diagrama, y el asistente lo lee cuando alguien pregunta por el algoritmo.

## Algoritmos sobre activos y modelos de proceso

Un algoritmo también puede trabajar sobre **activos**: una unidad, un horno, cualquier activo de
PlantCraft. Elija *Activos* en *Trabaja sobre*, luego nombre los activos y fije con qué frecuencia
se ejecuta (desde cada 10 segundos), hasta qué tiempo atrás lee cada ejecución y el paso con el que
lee. Sus bloques de señal leen un rol del activo, un rol de otro activo (un lazo de la unidad) o
una señal por su id. **Probar** lo ejecuta sobre la ventana de un activo, que termina ahora o en un
momento que usted elige; la página del algoritmo muestra su ejecución más reciente sobre cada
activo, y la página de un activo lista los algoritmos que se ejecutan sobre él.

La biblioteca **Modelos** contiene un bloque por modelo de proceso publicado (una FMU): sus
entradas son las entradas del modelo, más el valor medido de cada salida, y da lo que predice el
modelo y el residuo (medido menos predicho). Conecte los residuos a un bloque **Desviación (T²)**,
que los juzga frente a la operación normal.

La biblioteca **Sensores virtuales** contiene estimadores que no necesitan un modelo propio: un
filtro de Kalman de una PV a partir de su válvula, y una estimación de la deriva del sensor. El
algoritmo **Sensor virtual** conecta ambos sobre un lazo, los registra como series y juzga la
deriva con una verificación de límites.

Un modelo viene de PlantCraft Models: en la ejecución de una FMU exportada, un administrador
presiona **Publicar en Analytics**, y el modelo pasa a ser de inmediato un bloque de la biblioteca.
**Construir un algoritmo con él** allí (o **Algoritmo nuevo con este modelo** en la página del
bloque) abre el editor en un algoritmo nuevo sobre activos alrededor del modelo: un bloque de señal
en cada entrada y salida, el modelo, Desviación, un resultado y un mensaje. Elija el rol detrás de
cada bloque de señal, calibre, elija los activos y guarde.

**Calibrar** enseña al bloque Desviación cómo se ve lo normal. Seleccione el bloque, elija un
activo y un período en que la unidad operó normalmente, y presione *Calibrar*: el algoritmo se
ejecuta sobre el período como lo habría hecho, ejecución tras ejecución, y la media y la
dispersión de los residuos pasan a ser la calibración del bloque. Indica cuántas ejecuciones usó,
cuáles dejó fuera y por qué, y advierte cuando un residuo está lejos de cero (el modelo o un offset
de un sensor). Guarde el algoritmo para conservarla; hasta que un bloque esté calibrado no juzga
nada y lo indica.
