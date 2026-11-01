# Interacción entre lazos

## Qué detecta

Si el lazo se mueve junto con una segunda señal (la PV de otro lazo, una alimentación o un cabezal
de servicios): la mayor correlación absoluta entre ambas en un rango de desfases, con el desfase
en que ocurre. Una correlación fuerte es una pista de una perturbación compartida o de una
interacción.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control.
- Thornhill y Hägglund (1997), Detection and diagnosis of oscillation in control loops: una
  oscilación de toda la planta se manifiesta en varios lazos a la vez.

## Parámetros

- `max_lag_samples` (por defecto 60): el mayor desplazamiento, en muestras de la grilla, probado
  en cada dirección.
- `correlation_threshold` (por defecto 0.5): la correlación absoluta que puntúa 100; la puntuación
  es la mejor correlación dividida por ella.

## Cómo leer el hallazgo

"Correlación de 0.82 con la señal secundaria, con un desfase de 4 min." El signo indica si se
mueven juntas u opuestas; el desfase indica cuál va adelante. Revise la topología del proceso
antes de culpar a un lazo: la correlación no prueba causalidad.

## Límites

- Necesita una señal `secondary` en el lazo; sin ella el método informa datos insuficientes.
- Las perturbaciones comunes producen correlación sin ninguna interacción.
