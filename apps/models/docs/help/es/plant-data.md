# Simular con datos de planta

Una simulación puede tomar sus entradas del historial de la planta y dibujarse contra las propias
señales de la planta: ¿el modelo es correcto, y qué habría hecho la planta con otra sintonía?

En el diálogo **Simular** del editor de código (**Código** en la página de un modelo), marque
**Usar datos de planta**:

1. **Desde** y **Hasta**: el período del historial de la planta. La simulación lo cubre, empezando
   en el tiempo 0 del modelo.
2. **Paso de muestreo**: cada cuánto se leen las señales (en segundos). Un período puede contener
   hasta 100.000 muestras.
3. **Entradas de la planta**: cada entrada de nivel superior del modelo (un conector `RealInput` o
   una variable `input Real`) puede seguir una señal. Entre dos muestras se mantiene el último
   valor, tal como lo registró la planta.
4. **Comparar con la planta**: una variable del modelo (`tank.level`) y la señal con la que debería
   coincidir. El gráfico de la simulación dibuja las muestras de la señal junto a la variable.

Las señales se leen a través de PlantCraft con su propio acceso: usted ve las señales que
PlantCraft le muestra. El gráfico de una simulación así está en hora de la planta.

Para manejar un modelo desde la planta, dele entradas. En el ejemplo `TankLevelControl`, la
alimentación del tanque viene de una bomba; una copia con un `Modelica.Blocks.Interfaces.RealInput
qin` conectado al `qIn` del tanque puede alimentarse en su lugar con una señal de caudal.

La página de un activo en Models (abierta desde el activo en PlantCraft) lista las simulaciones que
usaron sus señales.
