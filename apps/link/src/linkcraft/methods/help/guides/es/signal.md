# Una señal

Los datos de una señal en la ventana del algoritmo, con los eventos que encontró cada verificación
dibujados en el gráfico (huecos, tramos congelados, picos, valores fuera de los límites), el
resultado de cada verificación y el historial de calidad.

Los usuarios de ingeniería pueden:

- **Verificar ahora**: juzgar de nuevo la señal en la ventana del algoritmo (se guarda), o en otra
  ventana (no se guarda).
- **Cambiar su configuración**: límites que sobrescriben los de PlantCraft, una señal de referencia
  para la verificación de deriva, verificaciones desactivadas o activadas para esta señal, y
  parámetros para sus verificaciones.
- **Desactivarla**: el algoritmo la omite.

Las señales con el rol de setpoint, modo o salida del controlador en un activo de PlantCraft omiten
la verificación de valor congelado: un setpoint y un modo son constantes por diseño, y una salida
que se mantiene quieta es el estado del lazo (una válvula saturada, el modo manual), que juzgan los
métodos de lazos. Actívela para una señal si lo desea.

## Análisis de laboratorio

Una señal de una fuente de archivo (CSV: análisis de laboratorio, entradas manuales) es
**muestreada** y no se juzga como una señal de proceso. Su valor se repite hasta el próximo
análisis y es normal que las muestras estén separadas por horas, así que omite las verificaciones
de valor congelado, ruido y resolución. La actualidad y los huecos se miden frente a su intervalo
de muestreo: una advertencia cuando un análisis se atrasa medio intervalo, malo a los tres
intervalos sin ninguno. El rango, los picos (saltos entre muestras) y la deriva todavía la juzgan.
El intervalo se lee de las propias muestras (4 h cuando hay muy pocas); fíjelo en **Intervalo de
muestreo**. **Muestreo** marca cualquier señal como de laboratorio o como continua, sea cual sea su
fuente.
