# Estudios

Un **estudio** ejecuta un modelo sobre una grilla de valores de parámetros y compara las
simulaciones: qué tamaño de tanque mantiene mejor el nivel, cuánta área de intercambiador de calor
es suficiente. Inicie uno con **Nuevo estudio** en la página Estudios y elija cualquier modelo, o con
**Nuevo estudio** en la página de un modelo, que abre la misma página con ese modelo elegido
(`/studies/new`).

## Configurarlo

| Campo | Significado |
|---|---|
| Parámetros | Cada parámetro de los bloques del diagrama mantiene el **Valor del modelo**, toma uno **Fijo** o varía en un **Rango** (desde, hasta, cuántos valores, espaciados uniformemente) o en una **Lista** de valores |
| Indicadores | Variables medidas en cada simulación; las señales de los scopes aparecen primero |
| Configuración de la simulación | Inicio, fin, intervalos, tolerancia y solver, tomados de la configuración de la simulación del modelo |
| Límite de tiempo por simulación | Opcional, en minutos: una simulación que tarda más se detiene |

Cada combinación de los valores variados es una simulación: 5 valores de `tank.A` y 3 de `tank.Cv`
dan 15. La **Vista previa**, junto al formulario, indica cuántas antes de empezar, qué varía y
aproximadamente cuánto tardan (según las últimas simulaciones de este modelo y el número de
workers). Por encima de 100 advierte; un estudio contiene como máximo 500 simulaciones, salvo que un
administrador cambie `MODELCRAFT_STUDY_MAX_RUNS`.

OpenModelica compila el modelo una vez y luego solo cambia los parámetros (el ejecutor conserva el
modelo compilado para los siguientes lotes del estudio, de hasta 10), por lo que un barrido cuesta
mucho menos que la misma cantidad de simulaciones separadas.

## Optimización: encontrar los mejores valores

En la página de nuevo estudio, **Encontrar los mejores valores** convierte el estudio en una
optimización: en lugar de todas las combinaciones, busca los valores de algunas entradas o
parámetros que hacen mejor un indicador, una simulación a la vez, cada una elegida a partir de los
resultados de las anteriores.

| Campo | Significado |
|---|---|
| Optimizar | En la tabla de parámetros, una entrada o un parámetro puesto en **Optimizar** recibe su valor **menor** y su valor **mayor** y, opcionalmente, dónde **empieza** el optimizador (el centro de los límites cuando está vacío). Hasta 10 |
| Objetivo | Una variable y uno de sus indicadores (valor final, sobreimpulso, tiempo de establecimiento, IAE, ...), para **Minimizar**, **Maximizar** o **Alcanzar un valor** (se minimiza la distancia al cuadrado hasta la meta) |
| Restricciones | Opcional: otros indicadores mantenidos por debajo o por encima de un límite (`tank.level` mayor ≤ 2.5). Hasta 10 |
| Método | **Automático** toma Nelder-Mead, o COBYLA cuando hay restricciones. **Nelder-Mead** (sin derivadas, sin restricciones), **COBYLA** (sin derivadas, con restricciones), **SLSQP** (gradientes por diferencias finitas, con restricciones; menos simulaciones en problemas suaves, pero cada paso cuesta una simulación por valor) |
| Máximo de simulaciones | El optimizador se detiene cuando los mejores valores ya no cambian, o aquí (60 por defecto) |

Los métodos son los de SciPy (`scipy.optimize.minimize`). Los valores se escalan a 0..1 entre sus
límites, por lo que los primeros pasos (un cuarto de cada rango) sirven para cualquier unidad. Una
simulación que falla le cuesta al optimizador un valor muy grande, por lo que se aleja de ella. La
mejor simulación es la que tiene el mejor objetivo entre las que cumplen todas las restricciones;
cuando ninguna las cumple, la más cercana a cumplirlas, y la página lo indica.

La página del estudio abre con el panel **Optimización**: cómo avanza, los mejores valores junto a
su inicio y sus límites, un enlace a la mejor simulación y un gráfico del objetivo de cada
simulación (las que no cumplen una restricción, en otro color) con el mejor hasta ahora. El resto
de la página se lee como la de cualquier estudio: cada simulación que pidió el optimizador está en
**Simulaciones**, con sus valores.

Cada instalación tiene un ejemplo: **Example: tune the PI for the least IAE** cambia el controlador
PI de `FirstOrderDeadTimeLoop` (ganancia `controller.k` de 0.1 a 4, tiempo integral `controller.Ti`
de 2 a 100 s, empezando lento en 0.4 y 60 s) para hacer mínimo el IAE de la medición `dead_time.y`,
con su sobreimpulso como máximo en 10 % (COBYLA). Termina cerca de k 1.2 y Ti 21 s. El IAE se mide
a partir del valor final de la variable, así que deje que la simulación se ejecute hasta que el
lazo se estabilice (aquí, 300 s). Para sintonizar un lazo propio, ponga su modelo de proceso
delante de un bloque PID y haga lo mismo.

Las optimizaciones son secuenciales (cada punto depende del anterior): unas 20 a 60 simulaciones
para dos o tres valores. El ejecutor compila el modelo en la primera y lo conserva, por lo que cada
paso siguiente solo lo ejecuta (aproximadamente un segundo cada uno para los ejemplos). Si PlantCraft
se reinicia durante una, continúa por sí sola en el siguiente inicio: el optimizador vuelve a pedir
los mismos puntos y las simulaciones que ya tiene responden de inmediato. **Cancelar el resto** la
detiene.

## Leer un estudio

- **Clasificación** ordena las simulaciones por un indicador y una estadística: valor final, menor,
  mayor, media, integral, **sobreimpulso** (cuánto pasó de su valor final, en %), **tiempo de
  establecimiento** (cuándo entró por última vez en la banda de 2 % alrededor de su valor final) e
  **IAE** (la integral del error absoluto respecto del valor final). **Mejor es** indica si gana el
  menor o el mayor; la mejor simulación queda resaltada y nombrada encima de la tabla. Haga clic en
  una simulación para abrirla.
- **Resultados** superpone una variable de cada simulación terminada. **Colorear por** un parámetro
  variado sombrea las líneas de claro (valor menor) a intenso (mayor); **Envolvente** dibuja la
  banda donde cae el 90 % de las simulaciones y su mediana. **Indicador contra un parámetro**
  grafica un indicador de cada simulación contra un parámetro variado.
- **Simulaciones** lista las simulaciones con los valores que usó cada una. Marque algunas y
  presione **Comparar estas** para superponer solo esas.
- **Estadísticas sobre las simulaciones** da, para cada indicador, la media, la desviación estándar
  y los percentiles sobre las simulaciones.
- **Lado a lado** dibuja un gráfico pequeño por valor de un parámetro variado, todos en la misma
  escala vertical, para que las salidas de cada opción queden una junto a la otra; dentro de cada
  gráfico, las líneas se sombrean según el otro parámetro variado.
- **Simular de nuevo con cambios** abre la página de nuevo estudio con la misma configuración.

**Cancelar el resto** detiene las simulaciones en ejecución del estudio y saca de la cola las que
están en espera. Una simulación que falla (un valor de parámetro que el modelo no admite) se marca
como fallida; las demás continúan.

## Exportar para Jupyter

**Exportar para Jupyter** descarga un .zip con:

| Archivo | Qué |
|---|---|
| `parameters.csv` | Una fila por simulación: su id, sus valores y sus indicadores |
| `results.csv` | Cada punto de cada simulación terminada: `run_id`, `time` y las variables |
| `study.ipynb` | Un notebook que lee ambos con pandas y grafica los indicadores |
| `study.json` | La configuración del estudio |
| `model/` | Los archivos Modelica del modelo tal como eran |

Ábralo en Jupyter, JupyterLab o VS Code. El notebook solo necesita pandas y matplotlib.
