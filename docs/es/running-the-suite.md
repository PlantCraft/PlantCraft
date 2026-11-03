# Ejecutar la suite

Lo que cuida un administrador una vez instalada la suite: su zona horaria, su estado, sus copias
de seguridad, sus actualizaciones y la app Operación. Cada página nombrada aquí está en PlantCraft,
bajo **Administración**, o en Operación.

## Zona horaria

La suite guarda y calcula todas las horas en UTC. Las pantallas las muestran en **Hora local**: la
zona horaria de la instalación, la misma para todos.

- **Configuración › Instalación** define esa zona, elegida de una lista. `install.sh` la inicia con
  la zona propia del servidor. Cámbiela cuando el servidor lleva otra hora (un servidor en UTC en
  una planta de Brasil, por ejemplo). Las horas guardadas nunca cambian, solo cómo se muestran y
  cuándo se ejecutan las programaciones guardadas en hora local.
- Dondequiera que un formulario pide una zona horaria (la programación de las copias de seguridad,
  un monitor de Analytics, las horas en que una alarma puede notificar, una importación CSV),
  ofrece primero **Hora local**, luego **UTC**, luego desfases fijos (UTC−1 … UTC−12,
  UTC+1 … UTC+14), y al final las ciudades, para las zonas con horario de verano. Una programación
  guardada en **Hora local** sigue a la instalación si su zona cambia más tarde.
- Cada persona elige en **Preferencias** (su menú, al pie de la barra lateral) si ve la hora local,
  UTC o, cuando está en otro lugar, la hora de su propio dispositivo. Esa elección se guarda para su
  cuenta y es la primera que le ofrecen sus formularios.

## Estado del sistema

**Estado del sistema** muestra cada servicio de la suite con su estado, CPU, memoria y reinicios. La
suite se verifica a sí misma cada 30 segundos; cuando una parte se detiene, cada administrador recibe
un mensaje en **Mensajes** (de "System") y un aviso en la parte superior de las páginas de
PlantCraft, y otro cuando vuelve. **Descargar el paquete de diagnóstico** guarda lo que necesita el
soporte: versiones, el estado de cada servicio y el final de su log, y la configuración sin ningún
secreto. Nunca bases de datos, datos de la planta ni claves.

### Certificados

**Estado del sistema › Certificados** lista los certificados que usa la suite, con la fecha en que
expira cada uno: el de HTTPS y los de las conexiones OPC UA de Historian. Cada administrador recibe
un mensaje 30 días antes de que uno expire y otro 7 días antes. **Renovar** crea un certificado nuevo
para el cliente OPC UA de Historian; descárguelo y haga que cada servidor OPC UA confíe en él, o su
conexión se detiene. El certificado de un servidor se renueva en el servidor y luego se acepta de
nuevo en su fuente; el certificado HTTPS se reemplaza en la carpeta `certs/` de la instalación.

## Copias de seguridad

La suite hace sus propias copias de seguridad mientras funciona, todos los días a la hora de
**Programación** (02:00 hora local por defecto), y verifica cada copia antes de contarla. Guarda 7
copias diarias, 4 semanales y 3 mensuales, y la que se tomó antes de la última actualización.

- **Hacer una copia ahora** toma una de inmediato. **Verificar de nuevo** (el escudo en la lista)
  vuelve a verificar una.
- Una vez por semana (el domingo a las 03:00 por defecto) el **simulacro de restauración** restaura
  la última copia buena en una copia separada de la suite, sin red y sin puerto, la inicia, la
  verifica y la elimina. La suite en funcionamiento no se toca. **Probar una restauración ahora** lo
  ejecuta de inmediato.
- **Restaurar** devuelve cada base de datos, configuración e imagen a como estaban en esa copia.
  Escriba el nombre de la copia y su contraseña para confirmar. La suite se detiene unos minutos; lo
  que había se deja de lado, no se elimina, y la suite vuelve a ello por sí sola si la restauración
  no queda sana.

Desde el servidor, `sudo ./install.sh --backup`, `--list-backups` y `--restore NAME` hacen lo mismo.

## Actualizaciones

Una actualización llega como un paquete firmado. En el servidor, desde la carpeta del paquete nuevo:

```bash
sudo ./install.sh
```

Verifica la firma, hace una copia de seguridad, actualiza y verifica la versión nueva. Cuando la
versión nueva no está sana, vuelve a la anterior por sí sola. **Actualizaciones** muestra la versión
instalada, sus notas de versión y cada actualización con su resultado.

## Operación

**Operación** está al lado de Desk en el selector de apps, para los administradores y para las
personas con el rol **Operación** (TI, o el equipo de un integrador, sin hacerlos administradores).

- **Estado**: la CPU y la memoria de cada app frente a su propio límite ("86 %, 3.4 de 4 CPUs"), la
  CPU, la memoria, la carga y el disco libre de la máquina, y los incidentes. La **disponibilidad**
  de cada app en 24 horas, 7 y 30 días deja fuera el mantenimiento planificado. Un administrador
  planifica una **ventana de mantenimiento** (ahora o más tarde, todas las apps o algunas, hasta 72
  horas); mientras dura, la vigilancia no avisa sobre esas apps.
- **La máquina y su perfil**: el estado de la suite nombra la máquina como la ve Docker, el **perfil
  de máquina** que dimensionó la suite (small, medium, large o xlarge) y el límite de CPU de cada
  servicio al lado de su uso. Cuando la máquina corresponde a otro perfil (se agregó más memoria, un
  perfil fijado a mano), lo nombra con el comando para aplicarlo en el servidor, `sudo ./install.sh
  --machine auto`. No se cambia nada desde la web.
- **Logs**: el log de cada servidor en una sola lista, con filtros de período, nivel, texto,
  solicitud y app, las advertencias y los errores más frecuentes, "La misma solicitud en todas las
  apps" y exportación a CSV.
- **Alertas de carga**: avisa a los administradores cuando una app o la máquina se mantiene por
  encima de un nivel (CPU o memoria al 80 % advertencia y al 95 % crítico, o errores registrados por
  minuto) durante 5 minutos. Los niveles se cambian en la página.
- **Solicitudes**: cualquiera pide ayuda con **Pedir ayuda** en su menú, en todas las apps, con la
  app y la página ya completadas; un registro del log y un incidente abierto tienen **Abrir una
  solicitud**. Cada cola puede tener un horario de trabajo, y cada prioridad una meta de primera
  respuesta y una de resolución; los relojes corren solo en horario de trabajo y se detienen
  mientras una solicitud está Bloqueada. Solicitudes muestra el tiempo que queda o cuánto se
  atrasó. El tiempo se registra en cualquier solicitud o acción, facturable o no.
- **Socios**: las empresas que trabajan en la planta (grupos de tipo **Empresa**), cada una con su
  coordinador, equipos, un responsable en la planta y un último día de acceso, después del cual
  nadie de ella inicia sesión. Socios muestra las personas, el acceso, las solicitudes abiertas y
  las horas del mes de cada empresa. Al terminar un mes, un administrador o el responsable aprueba
  sus horas, y el mes se cierra. Un responsable sin el rol Operación ve solo Solicitudes y Socios,
  para sus propias empresas.
- **Acceso temporal de soporte**: un administrador le da a una persona Operación por hasta 72 horas,
  con un motivo. Termina por sí solo o con **Terminar ahora**, se avisa a la persona, y ambas cosas
  quedan en el registro de auditoría.

## Desde el servidor

Estos se ejecutan en el servidor, desde la carpeta de instalación, como root:

- `./install.sh --security-check`: 36 verificaciones de la instalación, con una puntuación;
  `--format json`, `junit`, `sarif` o un informe de evidencias para una auditoría. Se pueden
  registrar excepciones con una fecha de fin.
- `./install.sh --rotate-admin-password`: una contraseña nueva para el administrador de emergencia,
  que se muestra una sola vez. La verificación de seguridad falla cuando esa contraseña tiene más de
  90 días.
- `./install.sh --machine small|medium|large|xlarge|auto`: dimensiona todos los contenedores a partir
  de una sola elección.
- `./install.sh --show-config`: el archivo de instalación (`/etc/plantcraft/installation.conf`) y si
  está aplicado. Sus valores ganan sobre la línea de comandos y `.env`.

El paquete también trae una plantilla de Zabbix (`monitoring/plantcraft_zabbix_agent.yaml`, Zabbix
7.0 y posteriores) que vigila la máquina, el disco libre y cada servicio con los mismos niveles que
las alertas de carga.
