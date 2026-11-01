# PlantCraft: guía de seguridad para TI y OT

Dos páginas que se entregan a los equipos de TI y de automatización del cliente con cada versión.
Describe el despliegue de la suite con Docker ([install-offline.md](../install-offline.md)). Los
elementos marcados como **planificado** están registrados en `docs/gaps.md` y todavía no se cumplen;
**parcial** dice lo que falta. La versión en inglés, [`docs/security-guide.md`](../security-guide.md),
es la de referencia; esta traducción la acompaña en cada versión.

## 1. Qué es y qué no hace

PlantCraft lee datos de proceso de un historiador (PI Web API), de servidores OPC UA o de archivos
CSV y sirve análisis (PlantCraft Analytics, Historian, View, Alarms y Models; repositorios
`linkcraft`, `histcraft`, `dashcraft`, `alarmcraft`, `modelcraft`) a los navegadores. **Nunca
escribe** en un DCS, PLC, PI ni servidor OPC UA: los conectores de datos (los de PlantCraft y los de
Historian) no tienen ninguna llamada de escritura. La planta de demostración (PlantCraft Simulator,
perfil `demo`) es una imagen aparte que PlantCraft e Historian solo leen. No envía nada a internet:
ni telemetría, ni verificación de actualizaciones, ni llamada de licencia, ni fuente web, ni CDN
(`tests/test_offline.py`).

**Los modelos de lenguaje están desactivados por defecto.** PlantCraft puede dejar que sus
especialistas respondan con un modelo de lenguaje que el administrador configura en Configuración ›
Modelos de lenguaje ([collaboration.md](../collaboration.md)): un modelo en la red de la empresa
(vLLM, Ollama, un gateway) o una API en la nube. Hasta entonces no se envía nada a ningún modelo.
`PLANTCRAFT_LLM=off` prohíbe los modelos en la instalación, diga lo que diga la configuración. Un
modelo en la red de la planta se alcanza por el conducto de planta Z4, así que `firewall.sh` debe
listar su `host:port`, como para un servidor PI. Un modelo en la nube se alcanza solo a través de
`llm-egress` (fila "Salida a LLM" abajo): PlantCraft en sí sigue sin resolver ningún nombre de
internet. Los **asistentes de IA** llegan a la suite en sentido inverso, a través del servidor MCP de
solo lectura (sección 4), también desactivado por defecto.

## 2. Dónde instalar (modelo Purdue)

En un servidor Linux en el **nivel 3** (operaciones del sitio, al lado del historiador) o en la **DMZ
industrial (nivel 3.5)**. Nunca en los niveles 0 a 2. Los usuarios llegan desde el nivel 3 o 4 por
HTTPS; lee desde el nivel 3 (PI) o desde servidores OPC UA que el equipo de OT expone al nivel 3. No
necesita ninguna conexión entrante desde los niveles 0 a 2 y no abre ninguna hacia el nivel 4 ni
hacia internet.

## 3. Zonas y conductos (IEC 62443-3-2)

```text
 Usuarios nivel 4/3 ──C1 HTTPS 443──▶ [edge: proxy] ──▶ [apps: PlantCraft, Analytics,
                                                          View, Historian, Alarms, Models]
                                                          │ (red interna, sin ruta de salida)
                                      [histdb: solo Historian y histcraft-db] (interna)
                                      [plant: PlantCraft, Historian] ──C2──▶ PI Web API 443, OPC UA 4840
                                      [demo: PlantCraft, Historian y el Simulator]
                                                          (red interna, sin ruta de salida)
```

| Zona o conducto | Qué contiene | Controles |
|---|---|---|
| Z1 Host | El servidor y Docker | Endurecimiento y parches del cliente; solo se necesitan Docker y SSH |
| Z2 Borde | Proxy (Caddy) | El único puerto publicado (443); TLS con el certificado del cliente o una CA local; sin API de administración; sin NAT de salida, así que no puede salir |
| Z3 Apps | PlantCraft (uid 10001), View (10006), Historian (10008), PlantCraft Alarms (10009), PlantCraft Models (10011), Analytics (10012) | Red Docker con `internal: true`: sin ruta fuera del host; las apps llegan a los datos de la planta solo a través de la API de PlantCraft con tokens firmados, salvo Historian (fila de abajo) |
| Base de datos de Historian | `histcraft-db`, el PostgreSQL de Historian (uid 10008) | Su propia red interna `histdb`, compartida solo con Historian: ningún otro contenedor (proxy, PlantCraft, Analytics, View) puede abrir una conexión con ella; sin puerto publicado; scram-sha-256 con una contraseña que solo tiene Historian |
| Recolección de Historian | Historian (perfil `histcraft`) | El historiador y la capa de datos de la suite: lee sus propias fuentes (OPC UA, PI Web API, archivos CSV en `data/histcraft-csv`, solo lectura), creadas en su página Fuentes, así que es el segundo componente en el conducto de planta Z4, bajo las mismas reglas de `firewall.sh`; también se une a la red interna `demo` para leer el Simulator. Las contraseñas de las fuentes se cifran con `data/histcraft/secret.key` |
| Gateway de Historian | `histcraft-gateway`: Telegraf, sin cambios y fijado por digest (uid 10008, perfil `histcraft`) | Lee las fuentes MQTT, Modbus TCP y SQL en el mismo conducto de planta Z4 y en `demo`, nunca en `histdb` ni `apps`. Su única configuración es `data/histcraft/gateway/telegraf.conf` (0600, montado en solo lectura), escrito por el colector de Historian: solo entradas de lectura (`mqtt_consumer`, `modbus`, `sql` con un SELECT verificado) y una salida, hacia el colector con un token. Sin puerto, sin otro secreto |
| Workers de cómputo | `compute-gateway` (uid 10020, la imagen de PlantCraft) y los ejecutores de las apps `linkcraft-executor` y `modelcraft-executor` (uid 10020), aquí y en otras máquinas (docs/compute.md) | Ejecutan el código que escriben las personas: los análisis de Analytics y el código de los bloques, los trabajos Modelica de Models. Los ejecutores no tienen ninguna red (`network_mode: none`), ningún secreto, una raíz de solo lectura, `/tmp` como tmpfs noexec, ninguna capability, `no-new-privileges`, límites de CPU, memoria y procesos y un límite de tiempo y memoria por tarea; su único vínculo es su carpeta en `data/compute-jobs/` (modo 0700), compartida con el gateway. El gateway guarda la credencial del worker, no abre ningún puerto y le pide tareas a PlantCraft en la red interna `compute` (otra máquina: por HTTPS); un administrador pausa o revoca un worker en Configuración › Cómputo. El runner de Models (imagen `modelcraft-runner`) es la única imagen que tiene un compilador de C (OpenModelica lo necesita); Models y el runner rechazan el código `external` y las funciones de archivo o de sistema antes de ejecutar un trabajo |
| Instalador | Servicio `installer` (uid 10005) | El único contenedor con el socket de Docker; ninguna red (`network_mode: none`), solo lectura, ninguna capability; actúa solo sobre paquetes firmados que verifica por su cuenta |
| Salida a LLM | `llm-egress` (uid 10014, la imagen de PlantCraft) | La única vía hacia un modelo de lenguaje en la nube: un proxy HTTPS en la red interna `llm` (solo PlantCraft y él mismo) con su propia ruta de salida (`egress`). Abre un túnel solo hacia el puerto 443 de los hosts de los proveedores que un administrador agregó en Configuración › Modelos de lenguaje (PlantCraft los escribe en `data/egress/allow.json`, que él solo lee), y nunca hacia un nombre que se resuelva dentro de la planta o del host. Sin proveedor en la nube, o con `PLANTCRAFT_LLM=off`: no abre nada. No guarda ninguna clave (la solicitud va cifrada de extremo a extremo), registra cada conexión y cada rechazo, y es el único contenedor que resuelve nombres de internet (`PLANTCRAFT_LLM_DNS`). Deje el servicio fuera para prohibir los modelos en la nube a nivel de red |
| Z4 Conducto de planta | PlantCraft e Historian | Salida hacia los hosts PI y OPC UA que registra el administrador; `firewall.sh` limita toda la red de la planta a esos pares `host:port` |
| Demo | el Simulator (solo con `--demo`), PlantCraft e Historian | Red Docker con `internal: true`: el simulador no tiene ruta fuera del host |
| DNS | Cada contenedor | Ninguna consulta de un nombre fuera de la suite sale del servidor: el proxy y el Simulator resuelven solo nombres de servicios, PlantCraft también salvo que `PLANTCRAFT_DNS` nombre el servidor DNS de la planta, y las apps están en redes internas. La única excepción es `llm-egress`, solo para los hosts de los proveedores |
| C1 Usuarios → Z2 | HTTPS | HSTS, cookies de sesión seguras, inicio de sesión obligatorio, 10 inicios de sesión fallidos bloquean 5 minutos |
| C2 Z4 → PI/OPC UA | HTTPS / OPC UA binario | Cuenta de servicio de solo lectura en PI; OPC UA anónimo o usuario/contraseña (**planificado:** firma y cifrado OPC UA) |

`tests/test_isolation.py` demuestra en CI que solo el proxy publica un puerto, que un contenedor de
app no tiene ruta de salida (una conexión a internet falla) y no puede alcanzar la red de la planta
ni la base de datos de Historian, que ningún contenedor resuelve un nombre externo, y que cada
contenedor se ejecuta como se describe en la sección 5.

## 4. Cuentas y acceso

- El inicio de sesión es obligatorio en este despliegue; la contraseña del administrador de
  emergencia se genera al instalar (24 caracteres aleatorios, archivo con modo 0600, nunca en los
  logs).
- Roles administrador, ingeniería, lectura y solo dashboards, con acceso por aplicación, aplicados
  por la API. Las apps reciben tokens de corta duración firmados con Ed25519 (15 minutos) y los
  verifican sin conexión (`docs/api-v1.md`). `tests/test_route_permissions.py` recorre cada ruta y
  falla en una que responda sin sesión o por encima del nivel de quien llama. **Parcial:** fuera de
  este despliegue con Docker el inicio de sesión todavía es opcional.
- Inicio de sesión corporativo (desactivado por defecto, `docs/corporate-login.md`): Active
  Directory o LDAP solo sobre LDAPS o StartTLS, e inicio de sesión único con OpenID Connect (PKCE,
  state, nonce, ID tokens firmados). Los grupos del directorio se mapean a niveles, apps y grupos;
  la cuenta de administrador de la instalación siempre inicia sesión localmente. **Todavía no:**
  SAML.
- Registro de auditoría central: quién cambió qué (personas, grupos, activos, apps, claves,
  configuración, copias de seguridad), en PlantCraft y en cada app (las apps escriben el suyo a
  través de `POST /api/v1/audit`), con el nombre de la persona, guardado en la base de datos de
  PlantCraft, más cada inicio de sesión, inicio de sesión fallido, inicio de sesión bloqueado y
  cierre de sesión con la dirección de la que vino y el método (local, LDAP, OIDC). Los
  administradores lo leen en Configuración › Registro de auditoría (filtros, búsqueda, descarga
  CSV); las filas solo se agregan.
- Enlaces de agenda de Desk (desactivados por defecto, `docs/desk.md`): cuando un administrador los
  activa y nombra los servidores permitidos, PlantCraft lee esas direcciones `.ics` por https cada
  15 minutos (2 MB como máximo, sin credenciales en el enlace, direcciones dentro de la red
  rechazadas). Importar un archivo `.ics` no necesita red.
- Acceso de asistentes de IA (desactivado por defecto, `docs/assistant-access.md`): un servidor MCP
  de solo lectura en `/mcp` a través del cual el asistente de IA propio de una persona lee la
  planta, con un token de acceso de esa persona (mostrado una sola vez, guardado como SHA-256, con
  vencimiento, revocable) y exactamente el acceso de esa persona. Nada escribe; cada llamada a una
  herramienta se audita; `PLANTCRAFT_MCP=off` lo prohíbe en la instalación.
- El Asistente de Desk (desactivado hasta que se configure un modelo de lenguaje,
  `docs/assistant.md`): lee la planta a través de las mismas herramientas de solo lectura, como la
  persona que pregunta, con un token emitido en cada lectura, y solo las apps que esa persona puede
  abrir; el servidor MCP aplica el mismo filtro de apps. Cada lectura se audita (`assistant.tool`);
  las respuestas están limitadas por persona y por día.
- Notebooks (desactivado por defecto, `docs/en/notebooks.md`): JupyterLite incluido en la imagen,
  así Python se ejecuta en el navegador de cada persona, nunca en el servidor, y lee la API v1 como
  esa persona. No se descarga nada en tiempo de ejecución (sin alternativa a PyPI). Solo las páginas
  bajo `/notebooks/lite/` reciben una Content-Security-Policy que también permite
  `'unsafe-eval' 'wasm-unsafe-eval'` (WebAssembly y el código que genera JupyterLab); todas las
  demás páginas mantienen `script-src 'self'`. En la computadora de una persona el mismo paquete lee
  con su token de acceso, en solo lectura, mientras Notebooks está activado.
  `PLANTCRAFT_NOTEBOOKS=off` los prohíbe en la instalación.
  Lo que una persona puede pedirle a la API v1 está limitado (Configuración › Notebooks: 120
  solicitudes por minuto y 2 lecturas a la vez por defecto, `plantcraft/api/usage.py`): cada
  solicitud con un token de acceso, y las lecturas de series desde un navegador a través del proxy;
  pasado ese límite solo esa persona recibe 429, y las lecturas propias de las apps dentro de la red
  interna nunca cuentan.
  El kit de Notebooks (una parte opcional del paquete, ofrecida con Notebooks, que un administrador
  puede quitar) ejecuta Python y JupyterLab en la computadora de la persona, escuchando solo en
  127.0.0.1; PlantCraft agrega al zip la dirección del servidor y el certificado público de la CA
  local, nunca un token. El token del kit dura como máximo 90 días, nunca más que el límite del
  administrador para los tokens (Configuración, 30 días por defecto), solo lee, y se guarda en la
  bóveda del sistema. La persona lo pega en la app una vez como código de conexión (mostrado una
  sola vez en la página con sesión iniciada): la dirección del servidor, el token y el SHA-256 de la
  CA local, que la app verifica antes de confiar en la CA. Un enlace nombra solo un servidor y un
  notebook; la app no ejecuta nada que venga con él. JupyterLab allí necesita una contraseña que la
  app crea en cada arranque. Cada archivo de los kits se fija por SHA-256 al construirlo; los kits
  todavía no tienen firma de código (Windows y macOS avisan en la primera apertura).
- Demo pública (`install.sh --public-demo`, desactivada por defecto,
  [public-demo.md](../public-demo.md)): los visitantes entran como visitas de una sola cuenta de
  lectura (unos pocos lugares a la vez, minutos cada uno; desde afuera la cuenta nunca inicia sesión
  con su contraseña); cada escritura de una cuenta de lectura responde 403 (solo pueden cerrar
  sesión y marcar mensajes como leídos), nunca llegan a un modelo de lenguaje (solo llegan las
  personas con rol de ingeniería y los administradores que creó un administrador; los usos de las
  apps siguen desactivados), cada visita está limitada a `PLANTCRAFT_PUBLIC_DEMO_RATE` solicitudes
  por minuto a través del proxy (429) y a unas pocas solicitudes en curso en cada app. Nunca la
  active en una instalación que tenga datos reales de la planta.
- Las contraseñas de las fuentes escritas en la interfaz se cifran en reposo con una clave guardada
  en la carpeta de datos.

## 5. Contenedores y datos

- Cada contenedor: usuario no root, sistema de archivos raíz de solo lectura, todas las capabilities
  de Linux eliminadas, `no-new-privileges`, límites de CPU, memoria y procesos, verificaciones de
  estado, política de reinicio. Las imágenes no tienen compilador ni gestor de paquetes (pip se
  elimina), salvo el compilador del runner de Modelica (fila Workers de cómputo arriba); las
  dependencias de Python se instalan desde wheels con hash verificado.
- Todo el estado está en una carpeta (`data/`, una subcarpeta por usuario de contenedor:
  `processcraft/`, `linkcraft/`, `dashcraft/`, `alarmcraft/`, `modelcraft/`, `compute-jobs/`,
  `histcraft/`, `histcraft-db/`, `proxy/`, `plantcraft/`). Las claves de las apps
  (`data/<app>-app-key`) y la contraseña de la base de datos de Historian
  (`data/histcraft-db-password`) son archivos con modo 0600 cuyo dueño es el usuario de la app,
  pasados como secretos de Docker. Ningún dato sale del servidor. Hacer una copia de seguridad
  significa copiar la carpeta de instalación; las actualizaciones hacen la copia automáticamente (la
  base de datos de Historian por bloques, con las herramientas propias de PostgreSQL) y
  `./install.sh --rollback` vuelve a la versión anterior. **Planificado:** `plantcraft rollback`
  para instalaciones sin Docker (G12). PlantCraft no cifra los datos en reposo: use el cifrado de
  disco del servidor si se requiere.

## 6. Instalar, actualizar y quitar

Paquete sin conexión por versión: imágenes `.tar`, archivo compose, instalador, SBOM, sumas SHA-256.
No se necesita internet para instalar, actualizar ni revertir. Desinstalación:
`./install.sh --uninstall` conserva los datos; `--purge` los elimina. **Versiones firmadas:** el
publicador firma `SHA256SUMS` (el hash de cada archivo, incluidas las imágenes) con una clave
Ed25519; el hash del paquete se verifica con `ssh-keygen` antes de desempaquetarlo, e `install.sh`
vuelve a verificar la firma antes de instalar y en cada actualización, contra los
`trusted-publishers/` de la instalación ([install-offline.md](../install-offline.md), sección 2).
Paquetes para x86_64 y arm64. **Planificado:** instalador de Windows sin derechos de administrador,
wheelhouse para instalaciones sin Docker (G11).

**Apps.** Los administradores agregan apps desde la página Apps (un archivo `.pcapp` firmado, el
catálogo en línea o la dirección de una app externa) o con `./install.sh --add <file>`
([app-package.md](../app-package.md)). Cada paquete se verifica contra las claves de publicador en
`trusted-publishers/` (firma Ed25519 del manifiesto, SHA-256 de la imagen y del SBOM); su
publicador, sus permisos y su SBOM se muestran antes de confirmar, y cada paso queda en el registro
de auditoría. Un paquete nunca puede pedir escribir en la planta (`plant_write`) ni alcanzar hosts
externos (`outbound`), ni definir su propio entorno, volúmenes o puertos. El token propio de cada
app se limita a sus permisos en cada ruta de la API v1: un paquete, a su manifiesto firmado; una app
del paquete de la suite, a los `[permissions]` del `app.toml` de su imagen, fijados en el
`release.json` firmado del paquete, así ninguna app se otorga más al arrancar. Enviar texto a un
modelo de lenguaje es un permiso propio (`write.llm`), y un uso de una app fuera del paquete de la
suite no tiene modelo hasta que un administrador le da uno. El catálogo en línea está desactivado
hasta que se define `PLANTCRAFT_APP_CATALOG_URL` y un administrador lo activa; las plantas aisladas
lo dejan desactivado.

El acceso al socket de Docker equivale a root en el host. Está confinado al servicio `installer`:
PlantCraft y las apps nunca lo reciben, y PlantCraft solo deja solicitudes en una carpeta que lee el
instalador. El instalador no tiene red, vuelve a verificar cada paquete con su propia copia de solo
lectura de las claves de confianza y ejecuta cada app con el mismo endurecimiento que la suite.
**Para desactivar las instalaciones**, defina `PLANTCRAFT_APP_INSTALL=off` en `.env` y no ejecute el
servicio `installer` (quítelo de `compose.yaml` o `docker compose stop installer`); la página Apps
entonces solo lista apps y registra apps externas.

## 7. Integridad de las versiones y cadena de suministro

Sumas SHA-256 de cada archivo y del paquete; imágenes base fijadas por digest; dependencias de Python
fijadas con hashes; SBOMs CycloneDX para las dependencias de Python y la interfaz web, más el SBOM
que lleva una imagen de app (`sbom/<app>.json`, hoy View); PostgreSQL se distribuye como la imagen
oficial fijada por digest. La CI ejecuta pip-audit y npm audit en cada cambio (falla ante cualquier
vulnerabilidad conocida en los paquetes Python distribuidos y ante las altas o críticas en los
paquetes npm distribuidos). **Parcial:** el SBOM todavía no lista los paquetes del sistema operativo
de las imágenes ni el binario de Caddy (G13).

## 8. Requisitos de componentes IEC 62443-4-2 (objetivo SL1; SL2 donde se indica)

| Requisito | Estado |
|---|---|
| CR 1.1 Identificación y autenticación de usuarios humanos | Cumplido: cuentas locales, Active Directory o LDAP, inicio de sesión único con OpenID Connect |
| CR 1.2 Identificación de procesos de software | Cumplido: claves de las apps y tokens de servicio firmados (API v1) |
| CR 1.5 / 1.7 Gestión de autenticadores, fortaleza de contraseñas | Cumplido: contraseñas con hash, al menos 8 caracteres, contraseña de administrador generada |
| CR 1.11 Intentos de inicio de sesión fallidos | Cumplido: por nombre y dirección, 5 intentos libres y luego una espera que se duplica de 15 s a 15 min, como máximo 100 intentos por dirección en 15 min |
| CR 2.1 Aplicación de la autorización | Cumplido en la API, con una prueba de permisos de cada ruta |
| CR 2.8 Eventos auditables | Sí: registro de auditoría central de los cambios en PlantCraft y en las apps, de las llamadas a herramientas de los asistentes de IA y de cada inicio y cierre de sesión, leído en Configuración › Registro de auditoría |
| CR 3.1 / 4.1 Integridad y confidencialidad de las comunicaciones | Cumplido en C1 (TLS); C2 depende de la configuración TLS de los servidores PI y OPC UA |
| CR 3.4 Integridad del software y de la información | Cumplido: sumas SHA-256, imágenes fijadas; versiones y paquetes de apps firmados (Ed25519) y verificados antes de instalar y actualizar |
| CR 5.1 Segmentación de red | Cumplido: zonas Z2 a Z4 de arriba (SL2) |
| CR 7.1 Protección contra denegación de servicio | Parcial: límites de recursos, limitación de inicios de sesión |
| CR 7.3 / 7.4 Copia de seguridad y recuperación | Cumplido: copias de seguridad en línea programadas (la base de datos de Historian completa e incremental), un simulacro de restauración, copia antes de actualizar, reversión |
| CR 7.7 Funcionalidad mínima | Cumplido: no root, solo lectura, sin capabilities, sin API de administración, sin herramientas de compilación (SL2) |
| CR 7.6 RE1 Informe legible por máquina de la configuración de seguridad | Cumplido: `./install.sh --security-check --format evidence` (abajo) |
| Depende del cliente | Endurecimiento del host, parches, seguridad física, cifrado de disco, logs centralizados |

### Verificación de seguridad

`./install.sh --security-check` (o `./security-check.sh` en la carpeta de instalación) verifica la
suite en funcionamiento contra esta guía y no cambia nada. Lee `docker inspect`, los archivos de la
carpeta y la respuesta HTTPS del proxy; nada sale del servidor. Cada una de sus 37 verificaciones
tiene un id estable (`PC-<area>-NN`: `INT` integridad, `CTR` contenedores, `NET` red, `TLS`, `SEC`
secretos, `ACC` cuentas, `AUD` registros, `REC` recuperación, `MIN` funcionalidad mínima, `HOST`),
una severidad, un resultado (pass, warn, fail, info, na), la evidencia que vio, cómo corregirlo y sus
referencias (IEC 62443-4-2 CR, NIST SP 800-53). La puntuación va de 0 a 100, ponderada por
severidad, y una advertencia cuenta la mitad.

- `--format json` da un documento para las herramientas propias de la planta, `--format junit` un
  informe de pruebas (una falla es un caso de prueba fallido) y `--format sarif` un informe de
  análisis de código.
- `--format evidence` da el informe de evidencias para una auditoría (IEC 62443-4-2 CR 7.6 RE 1,
  IEC 62443-3-3 SR 7.6): el alcance (host, carpeta, versión, id de la instalación), la configuración
  vigente de `.env` (se omite cualquier clave que nombre un secreto, contraseña, token o clave),
  cada requisito (CR 1.1, CR 3.4, ...) con las verificaciones que dan su evidencia y el peor
  resultado, las excepciones con su motivo y estado, cada verificación, y el SHA-256 de la
  verificación y de su catálogo con el resultado de `PC-INT-01`. Guárdelo con el registro de
  cambios de la planta.
- `--skip PC-HOST-03,...` deja verificaciones fuera de una ejecución. Para un riesgo que la planta
  acepta, use una excepción en su lugar.
- Excepciones: `security-exceptions.conf` en la carpeta de instalación (o `--exceptions FILE`), una
  línea por riesgo aceptado, `ID YYYY-MM-DD reason`:

  ```
  # riesgos aceptados, revisados por el responsable de seguridad de la planta
  PC-REC-01 2026-12-31 backups go to the plant NAS nightly (change 1234)
  ```

  Hasta ese día (UTC, inclusive) una advertencia o una falla de la verificación se informa como
  `excepted`, con el motivo: la mitad de los puntos, y no es una falla para el código de salida.
  Desde el día siguiente la verificación vuelve a informar su propio resultado, con "the exception
  expired on ...". Una línea con un id desconocido o sin fecha y motivo se informa y se ignora.
- `--url https://name` verifica la respuesta HTTPS en otra dirección.
- Código de salida 0: ninguna falla; 1: una falla; 2: la verificación no se pudo ejecutar.

Las severidades, los títulos y las referencias de las verificaciones son datos:
`security-checks.tsv`, en el paquete al lado del script y cubierto por su `SHA256SUMS` firmado. El
instalador guarda ese archivo como `release-SHA256SUMS` (y `release-SHA256SUMS.sig`) en la carpeta
de instalación, y `PC-INT-01` verifica el script y el catálogo contra él, con la firma verificada
con el propio OpenSSL del servidor contra `trusted-publishers/`. Una severidad bajada a mano, o una
verificación editada, hace fallar `PC-INT-01`.

El host en sí (sistema operativo, SSH, AppArmor o SELinux) es de la planta. La verificación informa
si el firewall del host y el cifrado de disco están activados. También incluye un benchmark del host
cuando el host tiene uno, y no exige ninguno:

- `PC-HOST-05` Lynis. Como root la verificación ejecuta `lynis audit system --quick`; si no, lee el
  último informe (`LYNIS_REPORT`, por defecto `/var/log/lynis-report.dat`). Aprueba con un índice de
  endurecimiento de 70 o más y sin advertencias.
- `PC-HOST-06` OpenSCAP. Como root, con el contenido de SCAP Security Guide para el sistema del host,
  la verificación evalúa su perfil de servidor CIS nivel 1, o el estándar (`OSCAP_PROFILE` nombra
  otro). Si no, lee un archivo de resultados XCCDF indicado como `OSCAP_RESULTS`. Aprueba cuando
  ninguna regla falló.

Sin la herramienta la verificación informa `na`. Una ejecución tarda como máximo
`SECURITY_CHECK_SCAN_TIMEOUT` segundos (900), y `--skip PC-HOST-05,PC-HOST-06` deja fuera los
benchmarks.

## 9. Contacto

Informe las vulnerabilidades como se describe en `SECURITY.md`.
