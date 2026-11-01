# Saturación de la salida

## Qué detecta

La fracción de la ventana en la que la salida del controlador estuvo en (o cerca de) uno de sus
límites. Una salida saturada significa que el controlador se quedó sin autoridad: la válvula está
totalmente abierta o cerrada y el lazo está, en la práctica, abierto.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. La saturación es
  uno de los indicadores básicos que enumera el estudio; la puntuación es una heurística de
  ingeniería.

## Parámetros

- `lower_limit` (por defecto 0): el límite inferior de la salida, en su unidad (0 para una salida
  en %).
- `upper_limit` (por defecto 100): el límite superior de la salida (100 para una salida en %).
- `margin` (por defecto 1): qué tan cerca de un límite debe estar una muestra para contar como
  saturada.
- `warning_fraction` (por defecto 0.05): la fracción saturada en la que la puntuación llega a 100;
  la puntuación es la fracción saturada dividida por ella.

## Cómo leer el hallazgo

"La salida del controlador estuvo en sus límites el 93% del tiempo." El desempeño (100% menos la
fracción saturada) se multiplica en la salud del lazo. Una salida saturada con la PV lejos del
setpoint significa que la válvula, la bomba o el setpoint no son adecuados para el servicio
(válvula subdimensionada, intercambiador ensuciado, un setpoint que el proceso no puede alcanzar).
La fricción estática no se puede evaluar mientras la salida está en un límite.

## Límites

- La saturación puede ser una restricción del proceso (un selector, un límite de diseño) más que
  una falla.
- Los límites de salida distintos de 0–100 se deben configurar.
