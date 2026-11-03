# Índice de varianza mínima

## Qué detecta

Cuánto está la varianza del lazo por encima de la menor varianza que cualquier controlador podría
alcanzar con el tiempo muerto del lazo: el índice de varianza mínima (Harris). Es la referencia
clásica de la evaluación del desempeño de lazos de control y solo necesita datos de operación de
rutina, sin prueba de escalón.

## Referencia

- Harris (1989), Assessment of control loop performance, The Canadian Journal of Chemical
  Engineering 67(5): la parte del error que cae dentro del tiempo muerto no se puede eliminar con
  la realimentación, así que su varianza es la referencia de varianza mínima; el índice es esa
  referencia sobre la varianza real.
- Horch e Isaksson (1999), A modified index for control performance assessment, Journal of
  Process Control 9(6): por qué el límite de varianza mínima a menudo está fuera de alcance en la
  práctica y un índice muy por debajo de 1 todavía puede ser un buen lazo.
- Bauer et al. (2016), The current state of control loop performance monitoring, Journal of
  Process Control: el uso del índice y sus trampas en la industria.

## Parámetros

- `dead_time_seconds` (por defecto 0): el tiempo muerto del lazo; 0 lo estima como el desfase, en
  muestras, de la mayor correlación cruzada entre los movimientos de la OP y los de la PV (una
  muestra cuando no hay OP).
- `ar_order` (por defecto 20): el orden del modelo autorregresivo ajustado al error de control; se
  eleva al tiempo muerto más uno cuando el tiempo muerto es más largo.
- `max_delay_samples` (por defecto 60): el tiempo muerto más largo, en muestras, que se busca
  cuando se estima a partir de la OP y la PV.
- `good_index` (por defecto 0.5): el índice igual o superior al cual el lazo puntúa como saludable;
  los lazos industriales bien sintonizados suelen estar entre 0.3 y 0.6.
- `poor_index` (por defecto 0.1): el índice igual o inferior al cual la puntuación es 100; la
  puntuación cae linealmente entre ambos.

## Cómo leer el hallazgo

"La varianza es 4.2 veces la referencia de varianza mínima (tiempo muerto de 7 muestras): una
nueva sintonía podría eliminar hasta el 76% de ella." Un índice cercano a 1 significa que el lazo
ya rechaza las perturbaciones casi tan bien como lo permite la realimentación; un índice bajo
apunta a un control lento u oscilante, en el que una nueva sintonía, una reparación de la válvula
o un feedforward pueden compensar. Revise el tiempo muerto que usó (`delay_source`: parámetro,
estimado o supuesto): uno estimado o supuesto debe confirmarse antes de actuar.

## Límites

- La varianza mínima es un límite teórico que suele necesitar un control agresivo y grandes
  movimientos de la OP; el índice dice cuánto se podría ganar, no que se deba.
- Un tiempo muerto erróneo desplaza el índice: uno más corto hace que el lazo parezca peor.
- Los cambios de setpoint, la saturación y el modo manual en la ventana lo distorsionan; no forma
  parte de los algoritmos incluidos y se agrega a un algoritmo cuando se desea.
