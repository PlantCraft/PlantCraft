# Tiempo en la banda de operación

## Qué detecta

La fracción de la ventana en la que la PV se mantiene dentro de la banda que acepta la operación
(para un tambor pulmón, entre sus niveles de operación bajo y alto), y cuánto del resto estuvo por
debajo o por encima.

Con límites fijados para el lazo (`lower_limit` o `upper_limit`), es un KPI simple de tiempo en
límites y se aplica a cualquier lazo. Con la banda por defecto de 20–80 se aplica solo a niveles
pulmón: lazos cuyo registro de activo dice `level`, o lazos con el algoritmo de nivel pulmón, que
fija `assume_surge_level`. En otros casos devuelve "No aplica" con el motivo y queda fuera de
la salud del lazo (no cuenta como cero).

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. El tiempo dentro
  de los límites de operación es un KPI industrial común.
- Jelali (2006), An overview of control performance assessment technology and industrial
  applications, Control Engineering Practice.
- Shinskey (1996), Process Control Systems: Application, Design and Tuning, McGraw-Hill, para la
  banda del nivel pulmón. La puntuación es la fracción del tiempo dentro de la banda.

## Parámetros

- `lower_limit` (por defecto 20): el límite inferior de la banda de operación, en la unidad de la
  PV.
- `upper_limit` (por defecto 80): el límite superior de la banda de operación, en la unidad de la
  PV; debe estar por encima del límite inferior.
- `margin` (por defecto 0): una tolerancia que se suma fuera de ambos límites antes de que una
  muestra cuente como fuera de la banda.
- `assume_surge_level` (por defecto false): ejecutar sobre un lazo cuyo registro de activo no
  indica el tipo de lazo; el algoritmo Nivel pulmón lo fija, porque elegir ese algoritmo dice que
  el lazo es un nivel pulmón.

## Cómo leer el hallazgo

"La PV estuvo dentro de la banda de 20 a 80 el 97% del tiempo (1% por debajo, 2% por encima)." El
desempeño es la fracción dentro de la banda y se multiplica en la salud del lazo. El tiempo por
debajo o por encima indica de qué lado buscar (una válvula subdimensionada, una perturbación que
el lazo no puede rechazar, una banda demasiado estrecha).

## Límites

- La banda por defecto de 20–80 supone un nivel pulmón en % del span: fije los límites, en la
  unidad de la PV, para usar el bloque en cualquier otro lazo.
- Los límites de operación pueden cambiar con la tasa de producción o la campaña.
