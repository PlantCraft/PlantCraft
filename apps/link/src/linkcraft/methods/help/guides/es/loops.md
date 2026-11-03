# De dónde vienen los lazos y su configuración

Los lazos vienen del catálogo de activos de PlantCraft: cada activo del tipo lazo de control, con
sus señales por rol (PV, SP, OP, modo, secundaria) y su registro (tipo de lazo, criticidad, acción,
controlador, relaciones). El registro se edita en PlantCraft.

El tipo de lazo y la criticidad dan a cada lazo su algoritmo inicial, sus parámetros y su peso en
el orden de prioridad (vea Valores por defecto del análisis por tipo de lazo). Un ajuste cambiado
en la página del lazo pasa a ser de Analytics desde ese momento: la página lo marca como "definido
aquí", y "Usar el registro del activo" lo devuelve.

Un activo de lazo sin señal para un rol que su tipo requiere (PV y OP) se lista como Registro
incompleto y no se analiza hasta que las señales se asignen en la página del activo en PlantCraft.

La criticidad del registro (baja, media, alta) pondera el orden de prioridad: los puntos perdidos
desde 100 se multiplican por 0.6, 1.0 o 1.5; la criticidad crítica (2.0) se fija solo aquí.

## En la página del lazo

- **Dónde pasó la salida la ventana**: la fracción de la ventana en cada banda de 5% de la salida.
  Un lazo que vive cerca de 0 o 100% está saturado; uno comprimido en unos pocos por ciento tiene
  poco margen.
- **Escalones de setpoint** (solo lectura): "Buscar escalones" lista cada cambio de setpoint de la
  última ventana que se distingue claramente del ruido de la PV y se mantuvo al menos diez
  muestras, con cómo le respondió la PV: sobreimpulso más allá del nuevo setpoint, tiempo de subida
  (del 10 al 90% del escalón), tiempo de establecimiento (hasta que la PV se mantiene dentro del 5%
  del escalón, más amplio cuando la PV es ruidosa) e IAE dividido por el tamaño del escalón, en
  segundos, para que se puedan comparar escalones de distinto tamaño. Una rampa corta de hasta tres
  muestras cuenta como un escalón; los escalones dados en manual quedan fuera. Las medianas están
  encima de la tabla.
- **Sugerir sintonía** (solo lectura): ajusta un primer orden con tiempo muerto de la OP a la PV en
  la última ventana y da ajustes PI por reglas Lambda (IMC) para tres velocidades: ajustada
  (lambda = tiempo muerto), moderada (lambda = constante de tiempo) y robusta (lambda = 3
  constantes de tiempo), con la acción del controlador. Los datos tomados en lazo cerrado son un
  experimento débil, así que tómelo como punto de partida para una prueba de escalón. La página
  indica por qué una sugerencia no es confiable: el ajuste explica menos de la mitad de la PV, la
  OP casi no se movió, o la constante de tiempo es más corta que una muestra. No se envía nada al
  controlador.
- **Registrar como referencia** (ingeniería): conserva la última ejecución del lazo como la que se
  usa para comparar, después de la puesta en marcha o de una nueva sintonía. La página muestra
  entonces la salud de entonces y la de ahora y, para cada método, su estado, el cambio de
  puntuación y el indicador que más se movió. Una referencia por lazo: registrar de nuevo la
  reemplaza.
