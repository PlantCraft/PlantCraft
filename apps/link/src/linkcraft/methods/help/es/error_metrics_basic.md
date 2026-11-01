# Error PV–SP

## Qué detecta

Cuánto se aleja la variable de proceso de su setpoint en la ventana: el error absoluto medio
(MAE), el RMSE, la integral del error absoluto (IAE), del error cuadrático (ISE) y del error
absoluto ponderado por el tiempo (ITAE), y la fracción del tiempo que la PV se mantiene dentro de
una banda aceptable alrededor del setpoint. Es la medida básica de seguimiento de un lazo que debe
mantener o seguir su setpoint.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Las integrales del
  error son las medidas de desempeño más usadas en las herramientas industriales que cubre el
  estudio, que ordenan toda la población de lazos de una planta según esos KPI. Un error en la
  unidad propia de la PV no se puede comparar entre lazos (un error medio de 1 no es nada para un
  flujo de 500 t/h y es mucho para 2 bar), así que el error se puntúa frente a una fracción de la
  escala de cada lazo. El valor por defecto de 4 % es una heurística de ingeniería, no una
  referencia de un artículo.

## Parámetros

- `error_tolerance` (por defecto none): un error absoluto medio absoluto, en la unidad de la PV,
  que puntúa 100 (el peor). Vacío: la tolerancia es `relative_tolerance_percent` de la escala del
  lazo. Un algoritmo o lazo que lo fija lo usa tal como se da.
- `acceptable_band` (por defecto none): una semiamplitud absoluta, en la unidad de la PV, de la
  banda alrededor del setpoint que cuenta como en el objetivo. Vacío: `relative_band_percent` de
  la escala.
- `relative_tolerance_percent` (por defecto 4): el error absoluto medio que puntúa 100, en
  porcentaje de la escala del lazo; un error de 1 % de la escala cuesta 25 puntos.
- `relative_band_percent` (por defecto 1): la banda en el objetivo, en porcentaje de la escala del
  lazo.
- `pv_span` (por defecto none): el span de ingeniería de la PV. Cuando se da, es la escala del
  lazo; vacío, la escala es el tamaño del setpoint (mediana de |SP|) en la ventana.

## Cómo leer el hallazgo

"Error absoluto medio PV–SP de 0.8; la PV estuvo dentro de ±0.5 del setpoint el 64% del tiempo."
El resultado también da la tolerancia que usó, la escala y su base (`pv_span`, `setpoint`, o
`absolute` cuando se dio una tolerancia o el setpoint está en cero).
El desempeño mostrado es 100 menos la puntuación, así que 100% significa sin error y 0% un error
igual o mayor que la tolerancia; se multiplica en la salud del lazo. Un error grande con la salida
fija en un límite apunta a saturación (vea Saturación de la salida); con la PV en ciclo, a
oscilación; con movimientos frecuentes del setpoint, a la actividad del setpoint más que a una
mala sintonía.

## Límites

- La PV y el SP deben estar en la misma unidad de ingeniería.
- Un error alto puede venir de restricciones, perturbaciones o un setpoint que el proceso no puede
  alcanzar, no solo de la sintonía.
- Sin un span, el tamaño del setpoint es la escala: correcto para PV lejos de cero (flujos,
  niveles, temperaturas en °C), demasiado estrecho para una mantenida cerca de cero (una presión
  manométrica, una diferencial). Dé a esos lazos su `pv_span` o un `error_tolerance` absoluto.
  PlantCraft todavía no guarda los rangos de las señales; cuando lo haga, el span podrá venir de
  allí (brecha G36).
- Aquí el error no se compara con lo que lograría el mejor controlador posible: eso es el índice
  de varianza mínima (Harris), `harris_index`.
