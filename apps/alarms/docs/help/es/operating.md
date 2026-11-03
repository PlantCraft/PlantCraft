# Operación de alarmas

**Alarmas** lista todas las alarmas y alertas en una tabla, primero las más urgentes: las alarmas
no reconocidas, luego las que retornaron a normal sin reconocimiento, luego las activas
reconocidas y luego las archivadas. **Necesita atención** (predeterminado) muestra esas; **No
reconocidas**, solo las que faltan reconocer; **Todas**, todas las alarmas que generaron las
reglas, incluidas las normales. **Solo las mías** muestra aquellas por las que usted o sus grupos
responden, y aquellas de las que una regla le notifica. Filtre por prioridad, estado o área
encima de la tabla, y marque filas para reconocerlas juntas.

Una fila abre la alarma: su estado, de qué trata, su regla y su acción correctiva, su valor con
el límite, su **Historial** (cada activación, normalización, reconocimiento, archivo y cambio)
y los **Mensajes enviados** sobre ella.

Una **alerta** (una regla puede generar alertas en lugar de alarmas, por ejemplo "Falló la
ejecución de Analytics") también aparece aquí, pero no necesita reconocimiento y no cuenta en
Desempeño.

## Estados

| Estado | Significado |
|---|---|
| No reconocida | Activa, y nadie la ha reconocido todavía |
| Reconocida | Activa, y un operador la vio |
| Retornó a normal, no reconocida | Volvió a normal antes de que alguien la reconociera |
| Archivada | No activa nada hasta que termine el archivo (una decisión del operador, con un motivo) |
| Fuera de servicio | No se evalúa en absoluto (una decisión de ingeniería, o su regla está desactivada) |
| Normal | Inactiva y reconocida |

Estos son los estados de ISA-18.2.

## Reconocer

**Reconocer** dice "la vi". Una alarma reconocida sigue en la lista mientras está activa.
**Reconocer todas** reconoce todas las alarmas de la lista. El mensaje en Mensajes de PlantCraft
también tiene un botón **Reconocer**: abre la alarma y la reconoce. Quién la reconoció y cuándo
se conserva en la bitácora y cuenta en el indicador de tiempo hasta el reconocimiento.

## Archivar

Archive una alarma molesta durante un tiempo fijo (de 15 minutos a 7 días) e indique por qué.
Mientras está archivada se sigue evaluando, pero no activa nada. Cuando termina el archivo, o
alguien la quita, una alarma que sigue activa se anuncia de nuevo y necesita un nuevo
reconocimiento.

## La página de una alarma

La página de una alarma muestra su estado, su señal con el límite y cada ocurrencia o, para una
alarma de un evento repetido, los eventos que contaron y el que la normalizó. **Cambiar la
regla** abre la regla de la que viene; **Poner fuera de servicio** detiene solo esta alarma.

Un visualizador ve todo; reconocer y archivar requieren acceso de editor a Alarms.
