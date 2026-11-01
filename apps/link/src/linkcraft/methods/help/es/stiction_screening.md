# Detección de fricción estática

## Qué detecta

El patrón de movimiento de una válvula de control que se traba: se queda trabada mientras el
comando se mueve dentro de la banda de pegado, luego desliza en un solo salto, y el lazo cicla. La
detección lee la fracción de los movimientos de la salida que están trabados y la fracción de
saltos justo después de un movimiento trabado (pegar y luego deslizar), mientras la PV oscila.
También lee la forma de una oscilación regular: una válvula que se traba hace que la salida del
controlador de un lazo autorregulado (y la PV de un nivel) cicle en triángulos, mientras que una
sintonía agresiva o una perturbación externa mantiene los ciclos redondeados, como una senoide.
Cuando la OP es la salida propia del controlador, también lee la fase entre la OP y la PV (Horch):
una válvula que se traba las desfasa alrededor de un cuarto de ciclo; la sintonía o una
perturbación las mantiene en fase o en contrafase.

## Referencia

- Choudhury, Thornhill y Shah (2005), Modelling valve stiction, Control Engineering Practice
  13(5): el modelo de banda de pegado y luego deslizamiento que busca la detección.
- Choudhury, Shah, Thornhill y Shook (2006), Automatic detection and quantification of stiction in
  control valves, Control Engineering Practice.
- He, Wang, Pottmann y Qin (2007), A curve fitting method for detecting valve stiction in
  oscillating control loops, Industrial & Engineering Chemistry Research 46(13): cada semiciclo se
  ajusta con una senoide y con un triángulo; índice = error de la senoide / (error de la senoide +
  error del triángulo).
- Horch (1999), A simple method for detection of stiction in control valves, Control Engineering
  Practice 7(10): la correlación cruzada entre la salida del controlador y la PV es impar con
  fricción estática y par con un problema de sintonía o una perturbación (lazos autorregulados).
- Jelali y Huang (2010), Detection and Diagnosis of Stiction in Control Loops (Springer): la
  saturación se descarta antes de una prueba de fricción estática.
- Thornhill y Hägglund (1997): la prueba de oscilación de la PV (pico de autocorrelación).

## Parámetros

- `movement_epsilon` (por defecto 0.05): el mayor movimiento de la salida, en %, que cuenta como
  trabado.
- `jump_threshold` (por defecto 0.5): el menor movimiento de la salida, en %, que cuenta como
  salto (deslizamiento).
- `min_autocorrelation` (por defecto 0.3): el pico de autocorrelación de la PV en el que la parte
  de oscilación de la puntuación es completa.
- `min_lag_samples` (por defecto 3): el menor desfase, en muestras de la grilla, buscado para el
  pico de autocorrelación de la PV.
- `jump_fraction_reference` (por defecto 0.1): la fracción de movimientos de pegar y deslizar en
  la que la parte de deslizamiento de la puntuación es completa.
- `lower_limit` (por defecto 0): el límite inferior de la salida; los movimientos que lo tocan
  quedan fuera.
- `upper_limit` (por defecto 100): el límite superior de la salida; los movimientos que lo tocan
  quedan fuera.
- `margin` (por defecto 1): qué tan cerca de un límite debe estar una muestra para quedar fuera.
  Una salida fuera de `lower_limit`–`upper_limit` (un registro normalizado) no se verifica por
  límites.
- `shape_index_high` (por defecto 0.65): el índice de ajuste de curva en el que la parte de forma
  de la puntuación es completa (0.5 es indeciso, 1 un triángulo puro).
- `min_half_cycles` (por defecto 4): los semiciclos regulares necesarios antes de juzgar la forma;
  los semiciclos cuyas duraciones se dispersan más de la mitad de su media no son una oscilación
  regular.
- `op_is` (por defecto valve_command): lo que registra la OP. Fije `controller_output` cuando sea
  la salida propia del controlador (la mayoría de los registros de DCS) para usar la prueba de
  Horch; con un movimiento de válvula registrado la prueba no es válida, porque con fricción
  estática la válvula también cicla en fase con la PV.
- `horch_even` (por defecto 0.8): con `op_is` = `controller_output`, una correlación cruzada en
  desfase 0 de al menos esta fracción de su mayor valor (un ciclo en fase o en contrafase) deja
  fuera la evidencia de forma. La relación siempre se informa como `horch_index`.

## Cómo leer el hallazgo

"Posible fricción estática en la válvula: salida trabada en el 83% de las muestras y saltando
justo después de trabarse en el 14%, con la PV oscilando. Esto es una detección preliminar;
confírmela en campo." Un diagnóstico fuera de la puntuación de salud: confírmelo con una prueba de
válvula (pequeños escalones de la salida en manual), la realimentación de posición o un método
completo de fricción estática antes de planificar el mantenimiento. "Fricción estática no
evaluada: la salida estuvo en su límite" significa una ventana saturada, donde la fricción
estática no se puede ver.

## Límites

- La parte de pegar y deslizar necesita una salida que muestre el movimiento de la válvula; la
  parte de forma necesita una oscilación regular durante unos pocos ciclos de la ventana. La
  prueba de Horch necesita la salida propia del controlador y un lazo autorregulado (un nivel se
  lee de otra forma). La elipse y la bicoherencia no están implementadas (brecha G28).
- Otras causas (una salida cuantizada, un posicionador lento, banda muerta) pueden verse
  similares.
