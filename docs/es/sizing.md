# Dimensionar el servidor

Qué tamaño de máquina necesita la suite, a partir de los números que medimos. Cada cifra de abajo
viene de `make bench-suite` (`ci/bench/suite_bench.py`, informes en `docs/bench/results/`) sobre la
suite 0.3.0 con todas las apps activas, salvo que diga "estimación".

## Respuesta corta

| Planta | Señales archivadas | Lazos / activos | Personas a la vez | CPU | RAM | Disco para un año de histórico y sus copias de seguridad |
|---|---:|---:|---:|---:|---:|---:|
| Pequeña (una unidad, un piloto) | hasta 1000 | hasta 250 | hasta 10 | 4 vCPU | 8 GB | 150 GB |
| Mediana (un área de la planta) | hasta 8000 | hasta 2000 | hasta 30 | 4 a 8 vCPU | 16 GB | 1 TB |
| Grande (un sitio completo) | 8000 a 30 000 | 2000 a 8000 | 30 a 100 | 12+ vCPU | 32 GB | 4 TB (estimación) |

La fila mediana es la escala "target" del benchmark, medida en una máquina virtual de 4 vCPU y
16 GB y en una Mac mini de 12 núcleos (Apple silicon). Las filas pequeña y grande son estimaciones a
partir de esos números: ejecute el benchmark en su propia máquina antes de confiar en ellas.

## Lo que medimos (escala target: 8000 señales, 2050 lazos)

| Paso | 4 vCPU, 16 GB | Mac mini de 12 núcleos |
|---|---:|---:|
| Historian escribiendo el archivo histórico | 29 000 valores/s | 52 900 valores/s |
| Una hora de valores crudos para 8000 señales (una solicitud cada 500) | 4.0 s, p95 478 ms | 3.2 s, p95 710 ms |
| Una tendencia de 24 h de una señal, p95 | 21 ms | 17 ms |
| Analytics: una ronda sobre todos los lazos | 106 s en el worker de cómputo (50 a 58 s antes de los workers) | 27 s |
| Analytics: verificar la calidad de todas las señales | 257 s en el worker de cómputo (64 s antes de los workers) | 40 s |
| Un dashboard de 24 tarjetas | 1.8 s | 1.0 s |
| PlantCraft con 4 procesos, 16 personas haciendo clic a la vez | 178 solicitudes/s | 433 solicitudes/s, p95 104 ms |
| Personas a la vez abriendo páginas (5 a 15 s entre páginas, una consulta pesada de los datos después del 30 % de ellas): p95 de la página | 10: 1.0 s, 50: 1.6 s, 100: 2.6 s | 10: 2.9 s, 50: 16 s (la demo en vivo; el único proceso web de Analytics es el límite) |

Pico de memoria por contenedor a esa escala (máquina de 4 vCPU): Analytics 1.0 GB, PlantCraft
1.0 GB, base de datos de Historian 1.0 GB, Historian 600 MB, Simulator 320 MB, colector 190 MB,
todas las demás apps por debajo de 150 MB. Unos 4.5 GB en total, así que 8 GB queda justo y 16 GB
deja espacio para el sistema, la caché de páginas y las copias de seguridad.

## Disco

- **El archivo histórico de Historian** es lo que crece. Con las señales del benchmark (un valor
  leído cada segundo, comprimido por desviación) ocupa cerca de 1.4 bytes por valor leído: cerca de
  **1 GB por día para 8000 señales**, 350 GB por año. Las plantas reales suelen comprimir mejor
  (las señales estables guardan pocos valores), y un escaneo de 5 s en lugar de 1 s lo divide por
  cinco. La retención de cada punto (Historian › Configuración) le pone un tope.
- **Las copias de seguridad** también viven en la carpeta de instalación: reserve espacio para
  cerca del **doble del tamaño de Historian** (una copia completa semanal y las incrementales
  diarias), o apunte las copias de seguridad a otro disco.
- **Todo lo demás** (las bases de datos de PlantCraft y de las apps, los logs, el paquete) queda
  por debajo de 10 GB.

La suite vigila su propio disco: Administración › Estado del sistema muestra el espacio libre y,
después de un día, en cuántos días se llena el disco al ritmo actual. Por debajo de 30 días avisa a
los administradores en Mensajes, antes de que algo se detenga.

## Medir su propia máquina

```bash
python3 ci/bench/suite_bench.py --prefix ~/PlantCraft --scale small    # unos 5 minutos
python3 ci/bench/suite_bench.py --prefix ~/PlantCraft --scale target   # unos 15 a 30 minutos
```

Para personas a la vez, `python3 ci/bench/load_users.py --prefix ~/PlantCraft` agrega 10, 30, 60
y 100 personas en pasos de 3 minutos y se detiene en el primer paso cuyas páginas tardan más de 3 s
en el p95. Cada llamada que hace es una lectura. `--heavy 0.3` agrega una consulta pesada de los
datos después del 30 % de las páginas (tendencias de 7 a 90 días, los 30 o 90 días de una señal, un
dashboard o un informe de 30 días), `--visitor` inicia sesión como el visitante de la demo pública,
y `--seed-days 90` primero les da a 160 señales del benchmark 90 días de histórico. Las pantallas
que abre se graban con un navegador mediante `ci/bench/record_pages.py`
(`ci/bench/load_pages.json`).

El informe queda en `docs/bench/results/` con el nombre de la máquina; `--compare` pone dos
informes lado a lado. Ejecútelo cuando la suite no esté en uso: escribe datos de prueba y los
elimina al final.
