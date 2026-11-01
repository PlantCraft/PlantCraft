# Notificaciones

Alarms avisa a las personas de las alarmas en **Mensajes** de PlantCraft y, cuando PlantCraft
tiene el correo electrónico configurado (Configuración › Correo electrónico) y la persona lo
permite en su perfil, por **correo electrónico**. Cada regla indica quién se entera de sus
alarmas, en la parte **Mensajes** de sus **Salidas**. El correo electrónico aparece allí una vez
que PlantCraft puede enviarlo.

## Quién

- **El responsable**: para una alarma sobre eventos, el responsable que nombra la app en sus
  eventos (en Analytics, el responsable del monitor); si no, el responsable de la regla. Es el
  predeterminado.
- Personas y grupos de PlantCraft (como "Operación U-100").
- Desactivado: las alarmas de la regla se muestran solo en Alarms.

## Cuánto y cuándo

| Parte | Significado |
|---|---|
| Agrupar durante | Todas las alarmas de la regla activadas dentro de este tiempo (5 minutos de forma predeterminada) se envían en **un** mensaje: "Lazo crítico 3 veces en 1 h: 12 lazos en la Unidad 100" |
| Recordar cada | Mientras una alarma siga activa y no reconocida, se envía de nuevo; reconocerla lo detiene. 0 nunca recuerda |
| También cuando se normaliza | Un mensaje también cuando la alarma vuelve a normal |
| Horarios | Siempre, **solo dentro** de cierto horario (un turno de día), o **solo fuera** de él (guardia), en la zona horaria de la regla. Cuando empieza el horario con una alarma todavía en espera, se entrega una vez |
| Si nadie la reconoce | Pasos de escalamiento: después de cierta cantidad de minutos, avisar a más personas, como **el coordinador** de los grupos notificados (definido en PlantCraft, Personas › Grupos) |

## Lo que llega a las personas: la filosofía de alarmas

Resumen › Desempeño › **Metas** contiene las metas de la instalación. Alarms las mide
(**Desempeño**, con las diez alarmas más frecuentes) y las usa para que los mensajes sean pocos.
Los valores predeterminados son las metas públicas de ISA-18.2 y EEMUA 191; alguien de Ingeniería
las cambia, y cada cambio queda en la auditoría de PlantCraft.

| Protección | Qué hace |
|---|---|
| Por prioridad | **Crítica** se envía de inmediato, una por una, sin agrupar y sin límite. **Alta** se envía como la agrupa su regla. **Media**, **baja** y todas las alertas esperan el **resumen del turno** (07:00 y 19:00 de forma predeterminada, en la zona horaria de la filosofía): un mensaje por persona con lo que esperó. Una regla puede pedir de todos modos **Siempre de inmediato** en sus salidas |
| Agrupación | Un mensaje por regla y ventana de agrupación, no uno por alarma |
| Un límite por persona | Nadie recibe más de 6 mensajes por hora de Alarms. Pasado ese límite, un aviso indica que hay más esperando en Alarms. Las alarmas críticas y los escalamientos siempre se envían |
| Avalancha | Más de 10 alarmas para una persona o grupo en 10 minutos: reciben **un** mensaje de avalancha ("Avalancha de alarmas: 23 alarmas en 10 min") en lugar de cada una, cada 10 minutos mientras dure; las alarmas críticas siguen llegando una por una. Alarms escribe el evento `alarmcraft.flood.started` |
| Repetitiva | Una alarma activada 3 veces en un minuto, o 10 en una hora, deja de enviar mensajes; el resumen la lista con lo que hay que cambiar (una banda muerta, un retardo a la activación) |
| Permanente | Una alarma activa durante más de 24 horas ya no se recuerda; el resumen la lista para revisión |
| Inhibición | Mientras la alarma "failed" o "stalled" de un monitor de Analytics está activa, las otras alarmas de ese monitor no se anuncian. Mientras la vigilancia de la suite informa que Historian o su colector están caídos (o el instalador en silencio, o Docker caído), tampoco se anuncian las alarmas de "sin datos" ni las ejecuciones fallidas: esa es su causa, ya comunicada a los administradores. Lo mismo mientras Historian informa su colector detenido; mientras informa una fuente desconectada, solo esperan las alarmas de "sin datos" de las señales de esa fuente |

## En Mensajes

Cada ocurrencia de una alarma es una conversación en Mensajes: la activación, los recordatorios,
los escalamientos y la normalización llegan en el mismo hilo, que vuelve a quedar como no leído
con cada uno. El mensaje tiene los botones **Reconocer** y **Abrir la regla** junto a Abrir, y el
filtro "Alarms" los encuentra. **Reconocer** reconoce la alarma de inmediato, en su nombre, sin
abrir Alarms (un acceso de solo lectura se rechaza). Las alarmas críticas y altas también
aparecen en cualquier app que tenga abierta, con los mismos botones. Una alerta no necesita
reconocimiento: su mensaje tiene solo **Abrir la regla**. Los mensajes que agrupan varias alarmas
abren Alarms, filtrado por su regla.

Una vez que la alarma se reconoce (aquí, en Alarms o por otra persona), se normaliza o se pone
fuera de servicio, su conversación queda **resuelta para todos** los que la recibieron: sale de su
conteo de no leídos, pierde sus botones e indica qué la resolvió ("Reconocida por ana",
"Normalizada"). Un mensaje que agrupa varias alarmas se resuelve cuando todas lo están. Una nueva
activación de la alarma es una conversación nueva.

## Silenciamientos

Un **silenciamiento** (Reglas › Silenciamientos) retiene los mensajes de algunas alarmas (áreas,
disciplinas o alarmas elegidas) durante un tiempo, con un motivo: una parada planificada, una
parada general. Las alarmas se siguen activando, mostrando y registrando. Para detener la alarma
en sí mientras se repara su instrumento, **suprímala** en su lugar (Operación de alarmas).

## Lo que se envió

La página de cada alarma lista sus **Mensajes enviados**: cuándo, a quién y si se envió. Cuando PlantCraft no puede recibir un mensaje (porque se está reiniciando, por ejemplo), este espera y
se vuelve a intentar en cada ciclo durante un día.

El diseño sigue descripciones públicas de herramientas de alertas (las reglas y la agrupación de
notificaciones de Grafana Alerting; la agrupación, la inhibición y los silenciamientos de
Prometheus Alertmanager) y la distinción de ISA-18.2 entre suprimir una alarma (shelving) y no
avisar sobre ella.
