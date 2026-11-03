# Stack

Las bibliotecas sobre las que está construida la suite, por área: qué usamos, su versión y licencia,
y dónde escribimos algo nosotros mismos que una biblioteca madura podría hacer en su lugar. Está aquí
para seguir el stack y decidir cambios cuando uno vale la pena. Las versiones son las fijadas en la
versión 0.3.0 (`deploy/requirements.lock`, `package-lock.json`, los digests de las imágenes en los
Dockerfiles); el inventario de licencias para la publicación está en `docs/publishing.md`.

Última revisión: 2026-10-23.

## Lenguajes y entorno de ejecución

| Qué | Versión | Licencia | Dónde |
|---|---|---|---|
| Python | 3.13 (`python:3.13-slim-trixie`) | PSF | El servidor de cada app |
| TypeScript | 5.8 | Apache-2.0 | Cada interfaz |
| Node.js | 22 (solo compilación) | MIT | Compila las interfaces; no está en las imágenes que se ejecutan |

## Backend (servidores web y API)

| Biblioteca | Versión | Licencia | Dónde |
|---|---|---|---|
| FastAPI | 0.148 | MIT | La API de cada app y la API v1 |
| Starlette | 1.9 | BSD-3 | Debajo de FastAPI |
| Uvicorn | 0.54 | BSD-3 | El proceso del servidor |
| Pydantic | 2.14 | MIT | Modelos de solicitudes y de configuración |
| httpx | 0.28 | BSD-3 | Cliente de la API v1 en el SDK, pruebas |
| requests | 2.34 | Apache-2.0 | PI Web API (con `requests-kerberos`, ISC) |
| itsdangerous | 2.2 | BSD-3 | Cookie de sesión firmada |

## Datos y cálculo

| Biblioteca | Versión | Licencia | Dónde |
|---|---|---|---|
| NumPy | 2.5 | BSD-3 | Métodos y bloques, compresión, alarmas |
| pandas | 3.0 | BSD-3 | Series en el SDK, métodos de Analytics, exportaciones |
| openpyxl | 3.1 | MIT | Mapa de la planta y archivo de configuración en Excel |
| ReportLab | 5.0 | BSD-3 | Informes PDF de Analytics |
| graphlib (biblioteca estándar) | Python 3.13 | PSF | Orden y verificaciones de un diagrama de bloques |
| FMPy | 0.3.32 | BSD-2 | Ejecuta FMUs (modelos de proceso) en Analytics |
| lxml | 6.1 | BSD-3 | Descripciones de FMU en Analytics |
| OpenModelica (`omc`) | 1.24.4 | OSMC-PL / GPL-3.0 | Contenedor de ejecución de Models, un programa aparte |

## Bases de datos

| Qué | Versión | Licencia | Dónde |
|---|---|---|---|
| SQLite (biblioteca estándar) | Python 3.13 | Dominio público | La base de datos propia de cada app |
| PostgreSQL | 17.11 | PostgreSQL | El archivo histórico de Historian |
| psycopg + psycopg-pool | 3.3 | LGPL-3.0 | La conexión de Historian con PostgreSQL |

## Conexiones con la planta

| Biblioteca o herramienta | Versión | Licencia | Dónde |
|---|---|---|---|
| asyncua | 1.1.8 | LGPL-3.0 | Cliente OPC UA (Historian) y servidor (Simulator) |
| Telegraf | como lo distribuye InfluxData | MIT | Gateway de Historian: fuentes MQTT, Modbus TCP y SQL |

## Interfaz

| Biblioteca | Versión | Licencia | Dónde |
|---|---|---|---|
| React | 19.2 | MIT | Cada interfaz |
| Vite | 7.3 | MIT | Compilación y servidor de desarrollo |
| Plotly.js (`plotly.js-cartesian-dist-min`) + `react-plotly.js` | 3.7 / 4.1 | MIT | Cada gráfico; `@plantcraft/ui` da el aspecto común (`timeChart`) |
| React Flow (`@xyflow/react`) | 12.12 | MIT | Editor de diagramas de bloques (`BlockEditor`, Analytics) |
| CodeMirror | 6 | MIT | Editores de código Modelica y Python (Models) |
| FullCalendar (`@fullcalendar/*`) | 6.1 | MIT | La agenda de Desk: año, mes, semana, día y lista; eventos creados y movidos arrastrando |
| Tiptap (`@tiptap/*`, sobre ProseMirror) | 3.31 | MIT | Las notas de Desk: texto enriquecido, listas de verificación y menciones `#` (solo las extensiones libres) |
| Lucide (`lucide-react`) | 0.468 | ISC | Íconos |
| Inter y JetBrains Mono (en `@plantcraft/ui`) | Fontsource 5.3 | OFL-1.1 | Fuentes tipográficas, incluidas (sin servicio de fuentes) |

## Inicio de sesión y seguridad

| Biblioteca o herramienta | Versión | Licencia | Dónde |
|---|---|---|---|
| cryptography | 50.0 | Apache-2.0 / BSD | Claves Ed25519, Fernet para las contraseñas de las fuentes, firmas del paquete |
| PyJWT | 2.15 | MIT | Tokens entre PlantCraft y las apps (`plantcraft_sdk.jwt`) |
| argon2-cffi | 25.1 | MIT | Contraseñas (Argon2id; los hashes PBKDF2 anteriores se migran al iniciar sesión) |
| joserfc | 1.7 | BSD-3 | ID tokens de OpenID Connect: firma y claims (`directory/jose.py`) |
| ldap3 | 2.9 | LGPL-3.0 | Inicio de sesión corporativo con LDAP o Active Directory |

## Empaquetado y ejecución

| Herramienta | Versión | Licencia | Dónde |
|---|---|---|---|
| Docker + Compose | 29 (CLI del instalador) | Apache-2.0 | Un contenedor por app, paquete sin conexión |
| Caddy | 2.11 | Apache-2.0 | El proxy HTTPS de la suite |
| Debian (`trixie-slim`) | 13 | Varias (DFSG) | Base de las imágenes |

## Pruebas y calidad

| Herramienta | Versión | Licencia | Dónde |
|---|---|---|---|
| pytest | 8 | MIT | Cada prueba de Python |
| Vitest + jsdom | 5 / 26 | MIT | Pruebas de la interfaz |
| Playwright | 1.64 | Apache-2.0 | Recorridos en el navegador (`make e2e`) |
| Ruff | 0.17.1 | MIT | Lint y formato de Python |
| ESLint | 9 | MIT | Lint de la interfaz |

## Escrito por nosotros, y qué podría reemplazarlo

Partes que escribimos nosotros mismos aunque exista una biblioteca, con la decisión de la revisión
del 2026-10-23. Los tres cambios que encontró que valían la pena están hechos: contraseñas con
Argon2id, tokens con PyJWT y tokens de OpenID Connect con joserfc (la biblioteca JOSE de Authlib). El
resto es **más adelante** (solo cuando ocurra el disparador de la nota) o **mantener** (una biblioteca
agregaría más de lo que quita).

| Nuestro | Dónde | Alternativa | Decisión |
|---|---|---|---|
| Copia de seguridad de Historian (`pg_dump`) | `plantcraft/apps/operations.py` | pgBackRest (MIT) | **Más adelante**: cuando el archivo histórico pase de unos 100 GB (ya planificado) |
| Particiones del archivo histórico de Historian | `histcraft/archive/partitions.py` | pg_partman (PostgreSQL) | **Más adelante**: si crece el mantenimiento de las particiones; la compresión y las agregaciones siguen siendo nuestras |
| Tabla de datos (orden, búsqueda, filtros, páginas) | `ui/src/DataTable.tsx` | TanStack Table (MIT) | **Más adelante**: cuando una lista sea demasiado larga para el navegador; la solución entonces es paginar en el servidor, algo que una biblioteca no da |
| Traducciones (`t()`, catálogos JSON) | `plantcraft/i18n`, `ui/src/i18n.ts` | i18next o FormatJS (MIT) | **Más adelante**: cuando la interfaz necesite un tercer idioma o plurales por idioma |
| Almacenes SQLite y migraciones hacia adelante | `sdk/python/plantcraft_sdk/server/store.py` (~170 líneas) | SQLAlchemy Core + Alembic (MIT) | **Más adelante**: si una app tiene que funcionar sobre otra base de datos |
| Firmas de las versiones (Ed25519) | `plantcraft/apps/release.py`, `deploy/bundle.sh` | minisign (ISC), Sigstore cosign (Apache-2.0) | **Más adelante**: cosign solo cuando las versiones sean públicas; necesita internet, el paquete no |
| Renderizador de Markdown | `ui/src/Markdown.tsx` | `react-markdown` + `remark-gfm` (MIT) | **Mantener**: es pequeño, no escribe HTML crudo y dibuja nuestros diagramas de flujo y de stack |
| Recorrido del producto | `ui/src/Tour.tsx` | Driver.js (MIT) | **Mantener**: cinco idiomas y el marco de la suite incorporados |
| Navegación entre páginas | `ui/src/nav.ts` (~60 líneas) | React Router (MIT) | **Mantener**: cada app tiene unas pocas páginas |
| Motor de bloques | `sdk/python/plantcraft_sdk/blocks` | pipefunc, PathSim (MIT) | **Mantener**: decidido el 2026-10-22, las bibliotecas eran jóvenes |
| Programaciones, cola de trabajos y pool de workers | `linkcraft/engine` | APScheduler, Procrastinate (MIT) | **Mantener**: harían falta dos bibliotecas (y PostgreSQL para Procrastinate) para hacer lo que hace el SQLite de la app |
| Compresión, bloques de datos y agregaciones de Historian | `histcraft/archive` | TimescaleDB | **Mantener**: swinging door es el método de los historiadores de planta, y la compresión de TimescaleDB está bajo la Timescale Licence, no es código abierto |
| Cliente de modelos de lenguaje | `plantcraft/specialists/model.py` | SDKs oficiales, LiteLLM (MIT) | **Mantener**: HTTP simple habla ambos formatos sin dependencias; desactivado por defecto |
| SBOM de una imagen | `sdk/python/plantcraft_sdk/sbom.py` | Syft (Apache-2.0) | **Mantener**: Syft ya se usa cuando está instalado; el nuestro es la alternativa sin conexión |
| Cliente de PI Web API | `histcraft/sources/pi_web_api.py` | Ninguno maduro y abierto | **Mantener** |
| Motor de alarmas (cifras de ISA-18.2) | `alarmcraft/engine` | Ninguno maduro y abierto | **Mantener** |
| Métodos de lazos de control | `linkcraft/methods` | Ninguno maduro y abierto en Python | **Mantener**; solo métodos públicos |
