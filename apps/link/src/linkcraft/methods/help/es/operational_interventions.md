# Intervenciones del operador

## Qué detecta

Con qué frecuencia intervienen personas (o una capa de supervisión) en el lazo: cambios de
setpoint más cambios del modo del controlador, escalados a una ventana de referencia. Un lazo que
necesita atención constante no está haciendo su trabajo, aunque su error parezca pequeño.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Contar las
  intervenciones del operador es una medida industrial común.
- Jelali (2006), An overview of control performance assessment technology and industrial
  applications, Control Engineering Practice. Incluye las intervenciones del operador entre los
  KPI prácticos de la CPA industrial. Los umbrales son una heurística de ingeniería; ajústelos por
  planta.

## Parámetros

- `sp_change_threshold` (por defecto 0.1): el menor movimiento del setpoint, en la unidad de la
  PV, contado como intervención; los movimientos más pequeños son ruido o redondeo.
- `reference_hours` (por defecto 12): la ventana, en horas, a la que se escala el conteo (un
  turno).
- `full_performance_max` (por defecto 2): hasta esta cantidad de intervenciones por ventana de
  referencia el criterio puntúa 100%.
- `zero_performance_min` (por defecto 12): a partir de esta cantidad de intervenciones por ventana
  de referencia el criterio puntúa 0%; entre ambos cae linealmente.

## Cómo leer el hallazgo

"3 cambios de setpoint y 1 cambio de modo en la ventana, equivalente a 2 intervenciones cada
12 h." Esto es contexto: se muestra junto a la puntuación de salud y nunca se multiplica en ella,
porque un operador muy activo no debe hacer que un buen controlador parezca malo. Muchas
intervenciones en un lazo con buena puntuación sugieren que los operadores no confían en él, o que
el setpoint lo maneja una receta o un APC.

## Límites

- Las recetas, el APC, los arranques y los cambios de grado mueven los setpoints a propósito.
- Necesita SP o modo; sin ninguno de los dos informa datos insuficientes.
- Una capa de supervisión que escribe el setpoint en cada muestra (el secundario de una cascada)
  cuenta cada escritura; no lo use en secundarios de cascada.
