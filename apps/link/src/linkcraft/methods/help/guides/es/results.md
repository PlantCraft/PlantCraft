# Resultados

Lo que concluyó cada algoritmo de Analytics, sobre cada activo en el que se ejecuta: una fila por
algoritmo y activo, el peor primero. Cada fila muestra el activo, su tipo, el algoritmo y su
versión, el estado en las palabras de la suite (OK, Advertencia, Alarma, Desconocido), la medida
del resultado (calidad, salud, puntuación), el hallazgo principal, las etiquetas del algoritmo y
cuándo se ejecutó.

Filtre por **algoritmo**, **etiqueta**, **tipo de activo**, **grupo** (el grupo responsable del
algoritmo) y **estado**, o busque por activo, hallazgo, algoritmo o etiqueta. Cada opción muestra
cuántos resultados conservaría. **Limpiar filtros** vuelve a mostrar todos los resultados.

**Informe** imprime como PDF lo que conserva el filtro: los conteos por estado y por algoritmo, y
luego cada resultado, el peor primero. Un filtro por la etiqueta *lazo de control* da el informe de
la cartera de lazos; cualquier otro filtro da el informe de lo que conserva.

Abra una fila para ver el resultado en su propia página; abra el activo para ver el resultado de
cada algoritmo sobre él. Los activos, incluidos los lazos, se registran en la página Activos de
PlantCraft: Analytics los lee y nunca mantiene su propia lista. La pestaña **Historial de
ejecuciones** lista cada ejecución de cada algoritmo.

## Controladores multivariables

La pestaña **Controladores multivariables** lee un controlador avanzado de terceros (APC, MPC) a
partir de sus propias señales y nunca escribe en él. Regístrelo en PlantCraft como un activo de
tipo *Controlador multivariable* con su señal `on` (1 cuando está encendido y en control), y dentro
de él un activo *Variable manipulada* o *Variable controlada* por cada MV y CV, cada uno con `value`
y, cuando el proveedor los da, `lo`, `hi`, `target` (meta de estado estacionario), `status` (1
cuando está en servicio) y `shadow_price`. El widget MV/CV de View lee los mismos activos.

Para cada controlador, durante el último día, semana o mes:

- **Encendido**: el tiempo que estuvo encendido.
- **MVs en servicio**: el tiempo medio que sus MV estuvieron en servicio mientras estaba encendido.
  Una MV fuera de servicio es libertad que el controlador no tiene.
- **CVs en un límite**: el tiempo medio que las metas de sus CV (sus valores, cuando no hay meta)
  estuvieron dentro de su banda de un límite. La banda es la *Banda en el límite* de la variable,
  o si no el 1% de su rango. Una CV en un límite es el controlador empujando la planta contra una
  restricción, no una falla.
- El estado es *Alarma* cuando el tiempo encendido, o el de MV en servicio, es menor que el 50% y
  *Advertencia* por debajo del 90%.

La página de un controlador ordena sus **límites activos por costo**: las horas que estuvo activo
cada uno, el precio sombra propio del controlador (la media mientras estuvo activo) y el **valor de
1% más de rango**, el precio sombra por el 1% del rango de la variable: lo que valdría mover ese
límite, en la unidad de costo del controlador. Un límite sin precio sombra se ordena por sus horas.
El informe semanal lleva las mismas dos tablas, y el widget *Analytics: controladores
multivariables* muestra cada controlador en el Resumen y en Desk.
