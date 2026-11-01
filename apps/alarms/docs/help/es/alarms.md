# Alarms

Alarms avisa a la persona correcta cuando algo necesita una acción. Las **reglas** leen dos cosas
y deciden:

- **Valores**: las señales de la planta y lo que las apps calculan y guardan como series, como la
  salud de un lazo en Analytics (un valor por ejecución).
- **Eventos**: lo que informan las apps de la suite, solo cuando algo cambia: una ejecución de
  Analytics que falló, una señal de Historian sin datos, un hallazgo abierto.

Una regla que se cumple activa una **alarma**; nada se vuelve alarma por sí solo.

## Por dónde empezar

El menú sigue el orden en que ocurren las cosas: llegan los eventos, las reglas los leen, se
activan las alarmas.

1. **Resumen** muestra las alarmas de un vistazo, en widgets que cada persona organiza; pase el
   cursor sobre el título de un widget para ver qué muestra y en qué orden. El widget de
   desempeño abre **Desempeño**, que compara la carga de alarmas con las **Metas** de ISA-18.2 y
   EEMUA 191.
2. **Eventos** lista lo que informaron las otras apps: **Abiertos ahora** (iniciados y no
   terminados) o **Todos** en un período, filtrados por tipo, app, activo, severidad o estado.
   Los eventos no notifican a nadie. Una fila abre el evento: de dónde vino (un enlace a la
   ejecución de Analytics que lo originó), lo que envió la app, los inicios y fines anteriores de
   la misma condición y las reglas que lo leen; **Crear una regla a partir de él** empieza una
   regla allí.
3. **Reglas** lista cada regla como una oración, cada una activada o desactivada desde la lista.
   **Nueva regla** escribe una en el formulario Simple o en Python. La pestaña
   **Silenciamientos** retiene los mensajes durante una parada planificada.
4. **Alarmas** reúne todas las alarmas en una tabla, primero las más urgentes: **Necesita
   atención** (predeterminado), **No reconocidas** o **Todas**, y **Solo las mías**. Una fila abre
   la alarma: su valor, su historial (cada activación, normalización, reconocimiento y cambio) y
   los mensajes enviados sobre ella.

## Una regla, muchas alarmas

Una regla cubre activos nombrados, todos los activos bajo una rama, todos los activos de un tipo,
los activos de un monitor de Analytics, o cualquier activo que nombren sus eventos, y genera
**una alarma por activo** de forma predeterminada: "PV por encima de 50 bajo la Unidad 100" es
una regla y una docena de alarmas. Cada alarma mantiene su propio ciclo de vida ISA-18.2
(activada, reconocida, suprimida), mientras que los mensajes de toda la regla se agrupan, así que
cincuenta lazos no se convierten en cincuenta mensajes. Vea **Reglas** y **Notificaciones**.

## De dónde vienen los datos

Alarms lee los valores y los eventos de la suite solo a través de PlantCraft, con su propia clave
de la app, cada pocos segundos. Nunca se conecta al sistema de control ni escribe en él: informa,
y el operador actúa. Una regla sobre activos lee el valor propio de cada activo (su rol `pv`, o
la serie de una app sobre él), así que cuando el mapa de la planta pasa un rol a otra señal, la
alarma lo sigue.

Cada activación y normalización también se envía a PlantCraft como un evento, y cada activo
muestra su estado de alarma en las otras apps (salvo que la salida **Dashboards** de la regla
esté desactivada).
