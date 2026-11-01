# Models

Models dibuja modelos de proceso como **diagramas de bloques** y los simula en el tiempo, como
Simulink: bloques con entradas y salidas se conectan entre sí, usted elige el inicio, el fin, el
solver y su paso, y **Simular** integra el diagrama. Detrás del diagrama está Modelica, el lenguaje
abierto para modelos de sistemas físicos, y OpenModelica lo calcula.

Models es para estudio: qué haría un tanque más grande u otra sintonía. Nunca se ejecuta sobre la
planta; los algoritmos que se ejecutan sobre los datos de la planta pertenecen a Analytics.

## Las palabras que usa Models

| Palabra | Qué es |
|---|---|
| **Bloque** | Una pieza con entradas, salidas y parámetros: un escalón, una ganancia, una función de transferencia, un PID, un tanque, un scope. Los bloques vienen en bibliotecas (**Bloques** en el menú). |
| **Modelo** | Bloques conectados en un diagrama, con su configuración de la simulación: un lazo de nivel, un intercambiador de calor. |
| **Simulación** | Una ejecución de un modelo: su configuración, sus resultados y sus mensajes. |
| **Estudio** | Un modelo ejecutado sobre una grilla de valores de parámetros, para comparar las simulaciones y encontrar la mejor. |
| **Simulaciones** (página) | Todo lo que se ejecutó: los estudios y las simulaciones individuales de cada modelo, con la cola. |

## Por dónde empezar

1. **Modelos** lista los modelos. Tres ejemplos están ahí desde el inicio: **TankLevelControl**
   (un PID mantiene el nivel de un tanque mediante su bomba de alimentación), **HeatExchangerOutlet**
   y **FirstOrderDeadTimeLoop**.
2. Abra **TankLevelControl**. Su página tiene las pestañas que tiene un algoritmo en Analytics:
   **Resumen** (qué es), **Entradas y salidas** (qué lee, qué muestran sus scopes y los parámetros
   de cada bloque: el predeterminado del bloque, salvo que el modelo defina su propio valor),
   **Diagrama** (el setpoint, el controlador, la bomba, el tanque, el transmisor de nivel y dos
   scopes; **Abrir el editor** lo abre en una ventana propia), **Probar**, **Usado por** (los
   estudios del modelo), **Versiones** y **Configuración** (desde cuándo hasta cuándo, con qué
   solver y paso, y dónde se guarda el modelo). Guardar un cambio genera una nueva versión y
   pregunta qué cambió.
3. En **Probar**, presione **Ejecutar la prueba**: una simulación con su configuración, una
   verificación. Los resultados grafican lo que muestran los scopes: el nivel siguiendo su
   setpoint.
4. Un estudio es lo que ejecuta un modelo de verdad: en **Estudios**, presione **Nuevo estudio**,
   elija el modelo, ponga `tank.A` en un rango de 2 a 6 con 5 valores y `tank.Cv` en la lista 0.03,
   0.05, 0.08: se inician quince simulaciones, y la página del estudio las clasifica por el
   indicador que usted elija y puede dibujarlas lado a lado, un gráfico por tamaño de tanque. Un
   valor que el estudio no define es el del modelo, y uno que el modelo no define es el
   predeterminado del bloque.

Los ejemplos se mantienen tal como vienen con Models. **Duplicar** hace su propia copia para
modificarla.

**Compilar**, en la página de un modelo, genera el modelo tal como está ahora y conserva con él la
versión compilada: una FMU (FMI 2.0, cosimulación), la forma que ejecuta Analytics. Junto al botón,
la página indica si el modelo está **Compilado** (y a partir de qué versión), **Desactualizado** (él,
o un bloque que usa, cambió después de la compilación), **La compilación falló** o **Sin
compilar**. La **Versión compilada** del Resumen indica cuándo y quién, cuánto tardó y qué dijo
omc, descarga la FMU y lista las últimas tres compilaciones. Probar y los estudios siguen
compilando en el ejecutor a medida que se ejecutan; un estudio reutiliza la compilación que
comparten sus lotes.

La página de un bloque tiene las pestañas de un bloque en Analytics: **Resumen** (cómo se dibuja,
qué hace, cómo leerlo y su fórmula), **Entradas y salidas** (sus puertos y parámetros),
**Código**, **Usado por** (los modelos que lo colocan) y **Versiones**. Los bloques que vienen con
Models se mantienen tal como están; **Duplicar** copia cualquiera de ellos a la biblioteca propia
de este sitio, donde sus valores predeterminados cambian en Entradas y salidas y cada guardado es
una nueva versión que indica qué cambió. Un valor definido en un modelo prevalece sobre el
predeterminado del bloque, y uno definido por un estudio prevalece sobre el del modelo.

Hay un solo tipo de modelo: un diagrama de bloques. Un modelo escrito en código Modelica (los
hornos de los que aprendió Analytics, por ejemplo) es un solo bloque de su propio diagrama: sus
entradas y salidas reales son los puertos del bloque y sus parámetros, la configuración del bloque.
Sus ecuaciones se quedan en el código, a un clic (**Código Modelica**).

## Quién puede hacer qué

| Rol | Puede |
|---|---|
| Lectura | Leer los modelos, bloques, estudios y simulaciones con sus gráficos y mensajes |
| Ingeniería | Todo lo demás: dibujar y guardar modelos, ejecutarlos, iniciar y cancelar estudios, exportar FMU, escribir bibliotecas de bloques |

## Dónde se guardan las cosas

Models guarda los modelos, las bibliotecas de bloques, las simulaciones, sus resultados y las FMU
en la carpeta de datos de la suite. Una simulación conserva una copia del modelo tal como era cuando
se inició, por lo que sus resultados siempre coinciden con el diagrama que los generó. **Código**,
en la página de un modelo, muestra su texto Modelica.
