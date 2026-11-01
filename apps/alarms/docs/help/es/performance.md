# Desempeño de las alarmas

La página Desempeño mide la carga de alarmas en un período (24 horas, 7 o 30 días) para un puesto
de operación, frente a las metas públicas de ISA-18.2 y EEMUA 191. Las alarmas suprimidas y fuera
de servicio no activan nada y no se cuentan.

| Indicador | Aceptable | Manejable |
|---|---|---|
| Alarmas por hora | hasta 6 | hasta 12 |
| Alarmas cada 10 minutos | hasta 1 | hasta 2 |
| Tiempo en avalancha (períodos de 10 minutos con más de 10 alarmas) | menos del 1 % | menos del 5 % |
| Pico de alarmas en 10 minutos | hasta 10 | hasta 20 |
| Carga de las 10 alarmas más frecuentes | hasta 5 % | hasta 10 % |
| Alarmas repetitivas (3 activaciones en un minuto) | ninguna | |
| Alarmas permanentes (activas durante más de 24 horas) | menos de 5 | menos de 10 |

La distribución de prioridades se compara con alrededor de 5 % alta (crítica y alta), 15 % media
y 80 % baja.

## El nivel EEMUA 191, las avalanchas y lo que dice la bitácora

- **Nivel EEMUA 191**: el período como un punto, promedio frente a pico de alarmas cada 10
  minutos, sobre las cuatro bandas de EEMUA 191: robusto, estable, reactivo y sobrecargado.
- **Avalanchas**: una avalancha de alarmas empieza por encima del límite de avalancha (10 alarmas
  en 10 minutos) y termina por debajo de la mitad, así que una pausa corta no la divide. Cada
  avalancha se lista con su duración, sus alarmas y su pico.
- **Horas por encima de 30 alarmas**: la fracción de las horas del período con más de 30 alarmas.
- **Alarmas fugaces**: alarmas que vuelven a normal en menos de 10 segundos sin que nadie actúe.
  Son candidatas a un retardo.
- **Tiempo hasta el reconocimiento** por prioridad, como la mediana y el percentil 90.
- **Alarmas más frecuentes**: las 20 que más se activan.

## Consolas (puestos de operación)

Las metas son para un operador. Cuando la planta tiene varias consolas de operación, defina las
**consolas** en Metas › Consolas. Cada consola lista:

- las **áreas** que atiende, en cualquier nivel del árbol de activos (una unidad, una sección, un
  equipo);
- quién la ocupa;
- su propia meta de alarmas por hora, si difiere de la carga por persona.

Una alarma va a la consola que nombra la más específica de sus áreas. Si dos consolas nombran la
misma área, va a la primera. Una alarma que ninguna consola cubre se cuenta bajo **Ninguna
consola**.

Desempeño muestra entonces una tabla **Consolas** con la carga de cada consola frente a su propia
meta: alarmas por hora, el pico en 10 minutos y el nivel EEMUA 191. El selector **Consola**
muestra cada indicador para una consola. Las personas que ocupan una consola ven primero la suya.

## Qué hacer con esto

Empiece por las **alarmas más frecuentes**: un puñado de alarmas problemáticas suele generar la
mayor parte de la carga. Para cada una, verifique el límite, agregue una banda muerta o un
retardo, o pregúntese si de verdad necesita una alarma. Las alarmas repetitivas casi siempre
necesitan una banda muerta. Las alarmas permanentes son o bien un problema real que persiste, o
bien una alarma que debería estar fuera de servicio.
