# Simular

**Simular**, en la página de un modelo, guarda el diagrama y lo simula con su **Configuración de la
simulación**:

| Configuración | Significado |
|---|---|
| Inicio, Fin | El período simulado, en segundos de tiempo del modelo |
| Solver | Cómo se integran las ecuaciones en el tiempo (abajo) |
| Paso | Con un solver de paso fijo, el paso de integración; con uno de paso variable, el paso de salida (un punto de resultado por paso) |
| Tolerancia | La tolerancia relativa de un solver de paso variable |

| Solver | Cuándo |
|---|---|
| DASSL (el predeterminado), IDA | BDF de paso variable: sistemas rígidos y la mayoría de los modelos de proceso |
| CVODE | Paso variable: sistemas suaves |
| Euler, Heun, Runge-Kutta | Paso fijo, explícito: sistemas no rígidos |
| Euler implícito, Trapecio | Paso fijo, implícito: sistemas rígidos con paso fijo |

Una simulación admite como máximo 200 000 pasos. La configuración se guarda con el modelo (su
anotación `experiment`), por lo que todas las simulaciones y estudios parten de ella.

Un modelo se ejecuta cuando cada entrada de cada bloque tiene una conexión; el diagrama marca lo que
falta. Se permiten lazos de realimentación (un controlador que lee el nivel sobre el que actúa).

## Los resultados

Los resultados debajo del diagrama grafican lo que muestran los **scopes** del modelo. Abra la
simulación para ver su propia página:

- las variables elegidas a la izquierda (hasta 12); **Principal** oculta las derivadas y las
  variables protegidas, **Todos** las muestra todas; cada una muestra su valor final;
- **Comparar con** dibuja las mismas variables de otra simulación del mismo modelo, con línea
  discontinua;
- **Resultados en CSV** descarga todas las variables en todos los puntos;
- **Mensajes** lista lo que dijeron OpenModelica y el solver.

Una simulación que falla queda marcada como **Falló** y sus mensajes dicen por qué: una ecuación que
no se pudo resolver, una división por cero, un paso demasiado grande para el solver.

## Simulaciones y la cola

**Simulaciones** está organizada como Resultados de Analytics, con el estudio en el lugar del
monitor y la simulación en el del activo. **Por estudio** lista cada estudio (y las **simulaciones
individuales** de cada modelo, lo que inicia Simular) con lo que varía y cómo terminaron sus
simulaciones; abra uno para ver un resumen y sus simulaciones, y una simulación para ver sus
resultados. **Cola** muestra lo que se ejecuta y lo que espera, ahora y a lo largo del tiempo (el
mismo panel que en todas las apps de la suite), y luego todas las simulaciones. Por defecto se ejecutan dos simulaciones a la vez (un administrador define
`MODELCRAFT_RUN_WORKERS`); las simulaciones individuales pasan antes que los estudios, por lo que
un estudio largo nunca bloquea una verificación rápida. Una simulación se detiene después de su
límite de tiempo (como máximo 6 horas, `MODELCRAFT_MAX_RUN_SECONDS`).
