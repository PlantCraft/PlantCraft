# Eventos

**Eventos** es lo que las otras apps de la suite informaron a PlantCraft. Las apps informan solo
cambios: una ejecución de Analytics que falló (un evento por ejecución, no uno por activo), una
señal de Historian que dejó de enviar datos y cuándo vuelve, un hallazgo abierto o cerrado.
PlantCraft descarta un inicio que ya está abierto y un fin de algo inexistente, y limita cada app
a 1000 eventos por hora, así que una app averiada no puede inundar la suite. Alarms los lee en
cada ciclo y los conserva 30 días.

Los eventos nunca notifican a nadie. Una regla decide cuándo un evento se vuelve una alarma.

## Abiertos ahora y Todos

**Abiertos ahora** (predeterminado) lista las condiciones iniciadas y aún no terminadas. Una app
informa una condición como dos eventos, su **inicio** y su **fin**, con una **clave** que la
nombra (un servicio, una señal, el hallazgo de un lazo). Una regla "abierto durante al menos
10 min" se activa con una condición así y se normaliza sola con su fin.

**Todos** lista cada evento del período (24 horas, 7 o 30 días), primero los más recientes.
Filtre por tipo, app, activo, severidad, estado (abierto, terminado, instantáneo) o si una regla
lo contó; **Reglas** nombra las reglas que contaron cada evento.

## Empezar una regla desde un evento

**Crear una regla** en un evento abre una regla nueva completada a partir de él: el tipo del
evento, el activo del que trata, abierto durante al menos cierto tiempo o contado cierta cantidad
de veces. Elija las salidas y luego presione **Probar** sobre los últimos días.

Cuando Alarms arranca por primera vez, muestra aquí los eventos del último día, sin contarlos: las
reglas evalúan lo que ocurre a partir de entonces.

Desde Analytics, **Crear regla de alarma** en un monitor abre una regla nueva ya completada para
él: cada activo en el que se ejecuta que resulte crítico, una alarma por activo, normalizada
cuando el estado vuelve a ok.
