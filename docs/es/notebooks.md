# Notebooks

**Notebooks** (en el menú de Desk, después de Agenda) es Jupyter dentro de PlantCraft: Python con
numpy, pandas, scipy y matplotlib, y los datos de la planta a una llamada de distancia. Se ejecuta en
su navegador, en su propia computadora (JupyterLite sobre Pyodide, incluido en PlantCraft: no se
descarga nada de internet), y lee la planta a través de la API v1 con **su propio acceso**: un
notebook nunca ve más de lo que usted puede ver.

## Ejecutar en el navegador

Desk › Notebooks tiene dos formas de ejecutar Python: **en el navegador** y **en su computadora**.

- **Instalar Python en este navegador** (una vez, unos 130 MB, con su progreso): la página trae
  Python, numpy, pandas, scipy, matplotlib y JupyterLab a este navegador. En la red de la planta
  tarda segundos (unos 15 s medidos); después la página verifica que siguen ahí y ofrece **Abrir
  JupyterLab** de inmediato. Una nueva versión de PlantCraft pide instalar de nuevo.
- **Abrir JupyterLab** abre una pestaña nueva con dos carpetas: **Examples** (notebooks listos que
  encuentran sus propias señales y activos, así se ejecutan en cualquier instalación, una carpeta
  por app: `PlantCraft` para los datos de la planta, `Link` para ejecutar bloques y algoritmos de
  Analytics, y una para cada otra app que trae ejemplos) y **My notebooks** (lo que PlantCraft
  escribió para usted). Mientras Python arranca, la página dice
  "Iniciando Python en su computadora…" (unos 10 s una vez instalado).
- Desde Historian (un punto, una exportación): **Abrir en un notebook**. PlantCraft escribe un
  notebook cuyas primeras celdas ya cargan esas señales en ese período, y lo abre en una pestaña
  nueva.
- Desde cualquier página, `/notebooks?signals=<id>,<id>&start=<time>&end=<time>` hace lo mismo, y
  `/notebooks?asset=<id>` abre un activo con sus señales.

Límites del navegador: la memoria que puede usar una pestaña (unos 2 a 4 GB), solo los paquetes que
vienen con él (sin `pip install` de otros), más lento que Python en su computadora para trabajo
pesado, y lo que usted cambia (también un ejemplo) lo guarda solo este navegador: **File ›
Download** guarda el notebook como `.ipynb`, y el botón de carga trae uno de vuelta. "En este
navegador", arriba a la derecha de JupyterLab, lo indica. Para más, ejecute en su computadora.

## Leer la planta

```python
import plantcraft_notebook as pc

pc.me()  # como quién lee el notebook
pc.signals("FIC")  # señales cuyo id, nombre o descripción contiene FIC
data = pc.series(["plant:FIC-101.PV", "plant:FIC-101.SP"], "-7d", "now", step=60)
data.plot(subplots=True)  # una columna por señal, un índice de tiempo en UTC
pc.value("plant:FIC-101.PV", agg="mean", window="24h")
pc.assets(type="loop")  # el árbol de la planta
pc.asset("FIC-101")["signals"]  # las señales de un activo por rol
pc.results(subject="asset:FIC-101")  # lo que publicaron las apps (salud del lazo, calidad...)
pc.events(ref="asset:FIC-101")  # hallazgos, alarmas activadas y normalizadas
```

Todas las horas son UTC: una hora sin desfase se toma como UTC, y `"now"`, `"-24h"` o `"-7d"`
cuentan hacia atrás desde ahora. `step` (segundos) da una media por paso; sin él, los valores tal
como se registraron. Los períodos largos y muchas señales se leen por partes.

## Los objetos de las apps

Todas las apps se leen igual en un notebook: `pc.app(...)` con el nombre de la app, y sus objetos
por tipo. Lo que ofrece cada app está en `pc.apps()`.

```python
link = pc.app("link")
link.kinds()  # block, algorithm
link.blocks()  # una tabla: lo mismo que link.list("block")
spikes = link.get("block", "dq.spikes")  # un objeto, completo: sus puertos y parámetros
run = spikes.run(asset="FIC-101", start="-24h")  # sobre la PV del lazo, aquí
run.values()  # cada salida: un resultado, un número, una serie
link.get("block", "transform.moving_average").run(x=my_series, window_samples=30)
link.get("algorithm", "flow").run(asset="FIC-101")  # un algoritmo completo sobre un lazo
link.runtime().test_block(block_file, x=my_series)  # un bloque que usted escribe, probado como lo prueba Link
```

Los modelos de Models se ejecutan en Models (OpenModelica), no en el notebook: `.run()` pone una
simulación en su cola, como lo hace su botón Simular, y `.wait()` vuelve a leer la ejecución hasta
que termina. Un administrador lo permite en Configuración › Apps › Models (**Simulaciones desde
notebooks**, desactivado por defecto), y solo pueden hacerlo las personas con rol de ingeniería en
Models. Las reglas y las alarmas de Alarms son de solo lectura: una alarma viene con sus ocurrencias
de los últimos 30 días, que es donde empieza un estudio de desempeño de alarmas. Los dashboards y los
informes de View también son de solo lectura, cada uno con sus paneles o secciones y las señales que
muestran (`pc.app("view").list("dashboard")`); el asistente los lista de la misma forma. Los
ejemplos de cada app muestran el resto: `Examples/Analytics`, `Examples/Models`,
`Examples/Historian`, `Examples/Alarms`.

```python
models = pc.app("models")
models.models()  # todos los modelos, primero los ejemplos
model = models.get("model", models.models().index[0])
run = model.run(stop=600).wait()  # en la cola de Models, cuando está permitido
run["results"]  # cada variable: su tiempo y sus valores (reducidos a 2000 puntos)
```

Un bloque o un algoritmo se ejecuta **en el notebook**, en su computadora o en este navegador, con
el código que ejecuta Analytics: el primer `.run` trae el entorno de ejecución de Analytics (su
código Python, menos de 1 MB, guardado por versión). Sus datos se leen con su acceso, como los lee
`pc.series`. Nada se ejecuta en el servidor y nada se escribe allí: para guardar un bloque, guarde
su archivo e impórtelo en Analytics. Los bloques de un modelo (una FMU) se ejecutan solo en
Analytics.

## Ejecutar en su computadora

Para más memoria, paquetes propios, archivos grandes o cálculos largos, ejecute los mismos notebooks
en JupyterLab en su propia computadora con **PlantCraft Notebooks**, una app para Windows (x64),
macOS (Apple silicon) y Linux (x64) que ofrece Notebooks › Ejecutar en su computadora mientras los
notebooks están activados y la instalación la tiene. Sin derechos de administrador, nada de
internet, ningún comando.

1. **Instálela una vez.** El botón nombra su sistema: un instalador para Windows (solo para usted,
   con una entrada en el menú Inicio y un desinstalador en Configuración › Aplicaciones), una app
   para macOS (arrástrela a Aplicaciones), una carpeta con `Install.sh` para Linux. Contiene Python
   3.12, JupyterLab, numpy, pandas, scipy y matplotlib (las versiones del navegador),
   `plantcraft-notebook` y los ejemplos. También hay un zip portátil que no necesita ninguna
   instalación.
2. **Conéctela una vez.** Notebooks › Ejecutar en su computadora › **Crear un código de conexión**
   da una línea (que se muestra una sola vez): la dirección de este PlantCraft, un token propio
   (solo lectura, como usted, por 90 días) y la huella de la autoridad certificadora de la
   instalación. Abra PlantCraft Notebooks (menú Inicio, Aplicaciones, su menú de Linux) y péguela
   cuando la pida; en el zip portátil, haga doble clic en Configure token. La app verifica la
   autoridad certificadora contra la huella, y guarda el token en la bóveda del sistema (Windows
   Credential Manager, el Llavero de macOS, el Secret Service en Linux; donde no hay ninguno, un
   archivo que solo usted lee). La app avisa cuando el token vence dentro de una semana: cree
   entonces un código nuevo.
3. **Abra notebooks.** Abra PlantCraft Notebooks: JupyterLab se abre en su navegador, con
   `Examples` y `My notebooks`. Una franja en la parte superior de JupyterLab dice que se ejecuta en
   su computadora y qué PlantCraft lee como quién. "Abrir en un notebook" (Historian, View, un
   activo) abre en el navegador; abra la app para tener en su computadora los notebooks que
   PlantCraft escribió para usted.

JupyterLab escucha solo en `127.0.0.1`, con una contraseña que la app crea cada vez que arranca, y
sigue ejecutándose en segundo plano (la app lo reutiliza; el menú Inicio o la app lo vuelven a
abrir). Los notebooks viven en `PlantCraft notebooks` en sus Documentos, fuera de la app, así una
nueva versión los conserva; el navegador no los ve, ni al revés. Cada apertura actualiza `Examples`
y copia los notebooks que PlantCraft escribió para usted en `My notebooks`, nunca encima de uno que
usted editó; en un notebook, `pc.sync()` hace lo mismo. `%pip install <name>` agrega cualquier
paquete, cuando su computadora alcanza un índice de paquetes.

La primera vez, Windows puede decir "Windows protegió su PC" (elija Más información y luego Ejecutar
de todas formas) y macOS que no puede verificar la app (Configuración del Sistema › Privacidad y
seguridad › Abrir de todas formas): la app todavía no está firmada. Un enlace solo nombra un
servidor y un notebook: la app se conecta solo después de que usted confirma, abre notebooks solo
para servidores ya conectados y no ejecuta nada que haya venido con el enlace.

**Sin el kit** (o en un Python propio: "Usar mi propio Python en su lugar"): **descargue** allí el
wheel `plantcraft-notebook` y conserve su nombre (pip rechaza un archivo que el navegador renombró,
como `...-2.whl`), instálelo en un entorno propio (macOS y la mayoría de los Linux rechazan un
`pip install` fuera de uno, PEP 668), **cree un token de acceso** y conéctese:

```sh
python3 -m venv ~/plantcraft-env            # Windows: py -m venv plantcraft-env
source ~/plantcraft-env/bin/activate         # Windows: plantcraft-env\Scripts\activate
pip install jupyterlab matplotlib ~/Downloads/plantcraft_notebook-<version>-py3-none-any.whl
jupyter lab
```

```python
import plantcraft_notebook as pc

pc.connect("https://<server>", token="pcat_...")  # o PLANTCRAFT_URL y PLANTCRAFT_TOKEN
```

Si su computadora no confía en el certificado del servidor, pase `ca="company-ca.pem"`. Las demás
celdas del notebook se ejecutan sin cambios; la línea `%pip install` de la primera celda es para el
navegador.

## Para administradores

- **Desactivado por defecto.** Un administrador activa Notebooks (PlantCraft › Configuración ›
  Notebooks), y cada cambio queda en el registro de auditoría (`notebooks.settings`, y
  `notebooks.create` por cada notebook que escribe PlantCraft). `PLANTCRAFT_NOTEBOOKS=off` en la
  configuración de la instalación los mantiene desactivados de forma definitiva.
- **Qué se ejecuta dónde.** El código Python se ejecuta en el navegador de cada persona, no en el
  servidor: el servidor solo sirve los archivos y responde la API v1 como esa persona. Un notebook
  pesado hace más lenta la computadora de esa persona, nunca el servidor de la planta.
- **Límites para cada persona.** Lo que un notebook le pide al servidor (series, señales, eventos)
  está limitado por persona en Configuración › Notebooks: 120 solicitudes por minuto y 2 lecturas a
  la vez por defecto. Cuentan cada solicitud a la API v1 hecha con un token de acceso (un notebook o
  un script en una computadora, un presupuesto por token) y las lecturas de series que el navegador
  de una persona envía a través del proxy. Pasado un límite, solo esa persona recibe `429` con
  `Retry-After`, y `plantcraft-notebook` espera y vuelve a preguntar por sí solo (hasta 4 veces, 30 s
  como máximo cada una). Las lecturas propias de las apps (Analytics, Alarms, View), dentro de la red
  interna, nunca cuentan, así un notebook pesado nunca las hace más lentas. El primer rechazo de cada
  minuto para cada persona queda en el registro de auditoría (`usage.limited`).
- **Qué puede hacer un notebook.** Exactamente lo que su persona puede hacer en PlantCraft a través
  de la API v1, con su propia sesión: leer señales, series, activos, resultados y eventos. Active
  Notebooks cuando se confía en que las personas ejecuten código que escriben o que les dan, como
  cualquier herramienta de análisis en su computadora.
- **Seguridad.** Las páginas de los notebooks (`/notebooks/lite/`) necesitan que el navegador ejecute
  WebAssembly y código que genera JupyterLab, así que la Content-Security-Policy del proxy, solo
  para esas páginas, también permite `'unsafe-eval' 'wasm-unsafe-eval'`. Aun así no cargan nada de
  fuera del servidor. Los tokens de acceso leen la API v1 solo mientras Notebooks está activado, y
  solo leen (`GET`, y la lectura de series `POST /api/v1/series`).
- La imagen lleva JupyterLite y un Pyodide reducido (unos 130 MB), construidos por
  `notebooks/build.py` con versiones y SHA-256 fijados en `notebooks/pins.json`.
- **El kit** es una parte opcional del paquete sin conexión (`notebook-kits/`, unos 450 MB para los
  tres sistemas), construido por `make notebook-kits` (`make bundle` también los construye; en la
  Mac mini, cada despliegue que los cambia) (`notebooks/kit/build_kit.py`: python-build-standalone
  y cada wheel fijado por SHA-256 en `notebooks/kit/pins.json` y `requirements.txt`). Se ofrece
  siempre que Notebooks está activado y la instalación lo tiene; un administrador puede quitarlo en
  Configuración › Notebooks › Kit para las computadoras de las personas. PlantCraft agrega a cada
  zip, al enviarlo, la dirección del servidor y, con la autoridad certificadora local, su
  certificado raíz; nunca un token. Cada descarga queda en el registro de auditoría
  (`notebooks.kit_download`), y también cada token del kit (`assistant_token.create`). Un kit se
  ejecuta en la computadora de la persona y lee solo a través de la API v1, dentro de los límites de
  arriba.
