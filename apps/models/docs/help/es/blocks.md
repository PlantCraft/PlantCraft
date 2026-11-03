# Bloques

Los **bloques** son con lo que se dibuja el diagrama de un modelo: cada uno tiene entradas, salidas y
parámetros. **Bloques**, en el menú, los lista por biblioteca. La página de un bloque tiene
pestañas, como la de un bloque en Analytics: **Resumen** (qué hace, sus entradas y salidas),
**Código** (su texto Modelica), **Entradas y parámetros** (una sola tabla, para que las columnas
se alineen) y **Usado por** (los modelos que lo colocan).

| Biblioteca | Bloques |
|---|---|
| Fuentes | Escalón, rampa, constante, seno, pulso, una tabla de valores en el tiempo |
| Matemáticas | Ganancia, suma, multiplicación, división, saturación, limitador de tasa |
| Continuos | Integrador, derivada, primer orden, función de transferencia, espacio de estados, tiempo muerto |
| Control | PID con anti-windup, on/off |
| Equipos de proceso | Tanque, bomba, válvula de control, intercambiador de calor, CSTR, retardo de medición |
| Sumideros | Scopes (una o dos señales): lo que los resultados de una simulación grafican primero |

## Usar un bloque

En el editor de un modelo (**Diagrama**, luego **Abrir el editor**), arrastre un bloque desde la
paleta al diagrama, o presione **+ Bloque**, y conecte una salida con una entrada. Seleccione un bloque para definir sus parámetros en el inspector; **Organizar** distribuye el diagrama
de izquierda a derecha.

## Escribir bloques

Las bibliotecas que vienen con Models son de solo lectura. **Nueva biblioteca de bloques** crea un
paquete Modelica vacío propio del sitio, con un nombre y una categoría, y lo abre en el editor de
código. Las entradas y salidas reales de un bloque (`RealInput`, `RealOutput`) se vuelven sus
puertos en el diagrama; sus parámetros, su configuración.

Cambiar un bloque cambia todos los modelos que lo usan, a partir de su próxima simulación. Las simulaciones ya hechas conservan
los archivos con los que se ejecutaron.
