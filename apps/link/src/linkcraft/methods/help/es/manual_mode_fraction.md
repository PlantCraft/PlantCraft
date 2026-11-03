# Modo manual

## Qué detecta

La fracción de la ventana en la que el controlador no estuvo en automático, a partir de la señal
de modo (textos como `MAN` o modos numéricos).

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. El tiempo en
  manual es el primer indicador industrial de CPM: un lazo en manual no entrega ninguno de sus
  beneficios.

## Parámetros

- `manual_labels` (por defecto manual, man, m): los textos de modo (en mayúsculas o minúsculas)
  que significan operación manual; agregue las etiquetas de su sistema (por ejemplo, `cas` es
  automático, `lo` puede ser manual).
- `warning_fraction` (por defecto 0.1): la fracción de la ventana en manual en la que la
  puntuación llega a 100; la puntuación es la fracción en manual dividida por ella.

## Cómo leer el hallazgo

"El lazo estuvo fuera de automático el 35% del tiempo." Esto es contexto, mostrado junto a la
puntuación de salud: comportamiento del operador, no desempeño del controlador. Un lazo en manual
durante la mitad de la ventana o más se marca como inactivo y no recibe puntuación de salud. La
operación frecuente en manual suele significar que los operadores no confían en el lazo: revise la
sintonía, la válvula y la medición.

## Límites

- La operación manual puede ser intencional (mantenimiento, arranque, condiciones anormales).
- Necesita una señal de modo con etiquetas confiables; los modos numéricos cuentan como manual
  solo cuando su valor está en la lista (`0` se lee como manual en la verificación del estado de
  operación).
