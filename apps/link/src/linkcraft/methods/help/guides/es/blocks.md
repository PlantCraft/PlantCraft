# Bloques

Todos los bloques que puede usar un algoritmo, en siete bibliotecas: elija una biblioteca a la
izquierda para ver sus bloques.

- **Entradas**: las señales del activo por rol (PV, SP, OP, modo…), y los resultados que Calidad de
  la señal ya les dio.
- **Calidad de datos**: la verificación de datos del lazo (se ejecuta primero en cada lazo; los
  métodos posteriores no se ejecutan con datos que rechaza) y las verificaciones que Calidad de la
  señal ejecuta sobre cada señal.
- **Transformaciones**: error, filtros, quitar tendencia, diferencia, recortar, retardo.
- **Desempeño de lazos de control**: seguimiento, oscilación, válvula, saturación, ruido y modo de
  operación; cada uno da un resultado y sus números clave.
- **Modelos**: un bloque por modelo de proceso publicado (FMU), que lo ejecuta sobre las señales
  del activo y da lo que predice y el residuo frente a la planta; el bloque de desviación (T²) que
  indica cuánto se aleja la planta del modelo; y cuándo la unidad está en operación.
- **Lógica**: peor de, promedio, regla, límites.
- **Salidas**: salud del lazo, un resultado en el activo, un mensaje, el resultado de una señal.

Un sitio agrega sus propias bibliotecas con **Nueva biblioteca**, debajo de las bibliotecas o junto
al campo Biblioteca en el formulario de un bloque; se listan después de las propias de Analytics.

Abra un bloque para ver qué hace, cómo leerlo, sus entradas y salidas, sus parámetros y sus valores
por defecto en este sitio, sus supuestos, límites y referencias, y su código fuente. Los
administradores cambian los parámetros por defecto de un método en su página; un tipo de lazo, un
algoritmo o un lazo todavía pueden sobrescribirlos.

**Duplicar**, junto a Descargar el archivo, inicia un bloque nuevo a partir de él, en la biblioteca
que usted elija. Un bloque de este sitio recibe su siguiente versión con **Nueva versión**, en su
pestaña Versiones; un bloque que incluye PlantCraft muestra allí un candado cerrado en su lugar:
cambia con PlantCraft, así que duplíquelo para hacer el suyo.
