# Atenuación de perturbaciones

## Qué detecta

Si un lazo de nivel de promediado (pulmón) hace su trabajo: absorber en el recipiente las
perturbaciones del caudal de entrada y entregar un caudal de salida suave. Compara cuánto recorre
la salida del controlador con cuánto recorre el nivel, ambos normalizados a sus rangos. Una salida
que se mueve más que el nivel transmite las perturbaciones aguas abajo en lugar de usar la
capacidad del recipiente.

Se aplica solo a niveles pulmón: lazos cuyo registro de activo dice `level`, o lazos con el
algoritmo de nivel pulmón, que fija `assume_surge_level`. En un lazo de flujo, presión,
temperatura o composición, o en un lazo cuyo registro no indica el tipo de lazo, devuelve "No
aplica" con el motivo y queda fuera de la salud del lazo (no cuenta como cero).

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. El control de
  nivel de promediado se juzga por el caudal de salida que transmite, no por el seguimiento.
- Shinskey (1996), Process Control Systems: Application, Design and Tuning, McGraw-Hill.
  Tratamiento clásico del control de nivel de promediado: el recipiente absorbe las
  perturbaciones para que el caudal de salida se mantenga suave. La relación de amplificación y
  sus umbrales son una heurística de ingeniería construida sobre esa idea; ajústelos por planta.

## Parámetros

- `pv_range` (por defecto 100): el span de la PV usado para normalizar su recorrido (100 para un
  nivel en %).
- `op_range` (por defecto 100): el span de la salida usado para normalizar su recorrido (100 para
  una salida en %).
- `full_performance_factor` (por defecto 0.5): la amplificación (recorrido normalizado de la OP
  sobre recorrido normalizado de la PV) que puntúa 100%: el caudal de salida se mueve la mitad que
  el nivel.
- `zero_performance_factor` (por defecto 1.5): la amplificación que puntúa 0%; entre ambas el
  desempeño cae linealmente.
- `movement_epsilon` (por defecto 0.01): el menor recorrido normalizado de la PV necesario para
  una relación estable; por debajo el método informa datos insuficientes (un nivel que no se
  movió).
- `assume_surge_level` (por defecto false): ejecutar sobre un lazo cuyo registro de activo no
  indica el tipo de lazo; el algoritmo Nivel pulmón lo fija, porque elegir ese algoritmo dice que
  el lazo es un nivel pulmón.

## Cómo leer el hallazgo

"La salida se mueve 1.8 veces el movimiento normalizado de la PV: el control transmite las
perturbaciones en lugar de absorberlas en el nivel." Un factor menor que 1 es lo que debe hacer un
nivel de promediado; por encima de 1 el nivel se mantiene demasiado ajustado (sintonía demasiado
agresiva para promediar) y las unidades aguas abajo ven las perturbaciones.

## Límites

- Solo para control de nivel de promediado; en un lazo de nivel ajustado un factor alto es
  intencional. Un nivel cuyo registro dice `level` pero que se mantiene ajustado necesita otro
  algoritmo.
- Los rangos erróneos de PV u OP hacen que la relación no tenga sentido.
- Un nivel que casi no se mueve no da una relación estable.
