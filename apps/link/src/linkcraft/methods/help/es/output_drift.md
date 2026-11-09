# Deriva de la salida

## Qué detecta

La salida del controlador avanzando siempre hacia el mismo lado, hora tras hora, mientras la PV
sostiene el setpoint. Un transmisor con deriva hace que el controlador sostenga la lectura
equivocada: la PV parece perfecta mientras el proceso se aleja, y el único rastro en los datos del
lazo es la salida siguiendo la deriva. El ensuciamiento, una válvula que se desgasta o una carga
que cambia despacio dejan el mismo rastro.

La ventana se divide en bloques (una hora por defecto); la deriva es el cambio mediano de la
mediana de la salida de un bloque al siguiente, contado solo entre bloques en los que el setpoint
se mantuvo, para que un escalón aislado (una calibración, un cambio de setpoint) no cuente.
Puntúa cuando la mayoría de los cambios va hacia el mismo lado.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. La medida es una
  heurística de ingeniería.

## Parámetros

- `block_minutes` (por defecto 60): la duración de los bloques cuya salida mediana se compara.
- `drift_per_day` (por defecto 6): la deriva, en % de la OP por día, que puntúa 100.
- `min_consistency` (por defecto 0.6): la fracción de los cambios entre bloques en el sentido de
  la deriva desde la cual cuenta.
- `full_consistency` (por defecto 0.8): la fracción en la que cuenta por completo.
- `min_blocks` (por defecto 8): el menor número de bloques con setpoint quieto para juzgar.

## Cómo leer el hallazgo

"La salida deriva hacia abajo cerca de 7 % por día (91% de los cambios entre bloques en el mismo
sentido) mientras el setpoint se mantiene: un transmisor con deriva, ensuciamiento o una carga que
cambia despacio." Un diagnóstico mostrado como alerta, fuera de la nota. Compare la PV con una
medición redundante, un resultado de laboratorio o un balance: un transmisor con deriva necesita
calibración. Si lee bien, busque ensuciamiento, desgaste de la válvula o una carga que cambia
despacio.

## Límites

- No distingue un transmisor con deriva de un cambio lento del proceso: confírmelo en campo.
- Una deriva calibrada de vuelta dentro de la ventana, o más lenta que ella, se lee más débil.
- Un lazo cuyo setpoint cambia cada hora tiene pocos bloques quietos para juzgar (sin resultado).
