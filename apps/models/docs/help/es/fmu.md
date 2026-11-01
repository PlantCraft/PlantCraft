# Exportar FMU

Una FMU (Functional Mock-up Unit) es un modelo empaquetado como un archivo estándar (FMI, la
Functional Mock-up Interface) que otras herramientas pueden ejecutar: PlantCraft Analytics y la
mayoría de las herramientas de simulación.

**Exportar FMU** (el botón del paquete en la página de un modelo, o en la barra de herramientas del
editor de código) genera una a partir del modelo:

| Opción | Significado |
|---|---|
| Versión FMI | 2.0 (la que leen más herramientas) o 3.0 |
| Tipo | **Cosimulación**: la FMU lleva su propio solver (CVODE) y avanza por sí misma; es lo que ejecuta PlantCraft Analytics. **Model exchange**: la herramienta que la ejecuta aporta el solver. **Ambos** |

La FMU se genera para Linux (64 bits), con sus bibliotecas incluidas, por lo que se ejecuta sin
OpenModelica. La exportación se ejecuta en la cola: su página muestra la versión FMI, la
plataforma, las entradas, las salidas y el
número de parámetros, y **Descargar la FMU**.

## Usarla en otro lugar

Descárguela con **Descargar la FMU** y úsela en cualquier herramienta que ejecute FMU. Las exportaciones se listan
en **Simulaciones › Cola**, con todas las simulaciones.

Models no envía FMU a Analytics: los modelos son para estudio y nunca se ejecutan sobre la planta.
Un modelo pensado para una herramienta que lo ejecuta contra la planta tiene entradas de nivel
superior (lo que la planta le da: caudales, aperturas, setpoints) y salidas (lo que predice:
niveles, temperaturas). Los ejemplos de **Analytics models** contienen los modelos que trae
Analytics para los lazos del Simulator.
