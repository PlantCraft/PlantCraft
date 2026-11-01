# Seguimiento de un modelo contra la planta

Un seguimiento verifica por su cuenta, de forma continua, un modelo contra la planta. Según una
programación, simula el modelo sobre la última ventana de datos de planta (como lo hace **Usar datos
de planta** en el diálogo Simular), escribe **modelo menos planta** para cada variable comparada como
una señal en PlantCraft y, cuando hay un límite definido, activa **Modelo alejado de la planta**
mientras el error se mantiene por encima de él.

Abra **Seguimiento** y presione **Nuevo seguimiento**:

1. **Modelo**: el modelo que se va a ejecutar. Su configuración (solver, parámetros) es la que tiene
   cuando se inicia cada ejecución.
2. **Ventana** y **Cada**: cada ejecución cubre los últimos *ventana* minutos hasta ahora, y una
   ejecución se inicia cada *cada* minutos (5 minutos como mínimo para ambos).
3. **Comparar con la planta**: una línea por variable, `variable = signal`, por ejemplo
   `tank.level = plant:LT-101`. Cada una recibe una señal de error,
   `app-modelcraft:tracking-<id>.<variable>.error`, escrita en los tiempos de muestreo de la planta
   dentro de la ventana. Grafique su tendencia en View, úsela en Analytics o configure una alarma
   sobre ella como con cualquier señal.
4. **Entradas de la planta** (opcional): las líneas `input = signal` alimentan las entradas del
   modelo desde la planta, manteniendo el último valor entre muestras.
5. **Límites de alarma** (opcional): `variable = number`, el error absoluto medio por encima del cual
   la variable está alejada de la planta. El evento se abre cuando una ejecución termina por encima
   del límite y se cierra cuando una termina por debajo; se envía al responsable del seguimiento
   cuando permanece abierto durante 30 minutos.

Cada ejecución es una simulación común entre las simulaciones rápidas del modelo, con la etiqueta
del nombre del seguimiento; se conservan las últimas 20 de cada seguimiento. La tabla muestra el
error absoluto medio y el sesgo de cada variable en la última ejecución, la ejecución en sí y por
qué falló cuando falló (una señal que no se pudo leer, un modelo que no compila). **Ejecutar ahora**
inicia una de inmediato; desmarque un seguimiento para ponerlo en pausa.

Los seguimientos leen la planta con el acceso propio de Models (la cuenta de servicio de la suite),
no con el de la persona que los creó: siguen ejecutándose cuando nadie tiene la sesión iniciada.
