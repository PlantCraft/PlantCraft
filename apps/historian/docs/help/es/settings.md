# Configuración

Los administradores definen cómo se leen, se comprimen y se conservan las señales. La
configuración tiene tres niveles, y prevalece el más específico:

1. **General** (esta página): todas las señales de todas las fuentes.
2. **Fuente**: una fuente puede definir su propio valor para sus señales (Fuentes, Editar,
   "Configuración de las señales de esta fuente"). Los campos vacíos toman el valor general.
3. **Señal**: una señal puede definir su propio valor (su página, "Recolección y compresión").
   Los campos vacíos toman el valor de la fuente o, si no, el general.

| Configuración | Valor general predeterminado | Significado |
|---|---|---|
| Retención (valores brutos) | 400 días | Los valores más antiguos que esto se eliminan cada hora (en PostgreSQL, un mes pasado cuyos valores superaron todos la retención se descarta de una vez) |
| Agregaciones horarias | 1825 días (5 años) | Valor medio, más bajo y más alto de cada hora, conservados después de que se eliminan los valores brutos; solo general |
| Agregaciones diarias | para siempre (0) | Las de cada día UTC, a partir de las agregaciones horarias; solo general |
| Agregaciones mensuales | para siempre (0) | Las de cada mes UTC, a partir de las agregaciones diarias; solo general |
| Escaneo | 1 s | Segundos entre dos lecturas |
| Desviación | 0.1 % | Del rango de la señal cuando se conoce el rango; si no, del valor (cada valor archivado empieza un segmento que se mantiene dentro de esa fracción de él; cerca de 0 se conserva casi cada cambio). Una señal la define en unidades de ingeniería |
| Intervalo máximo | 3600 s | Un valor se archiva al menos con esta frecuencia, incluso en una señal plana |

La página de una señal indica lo que está vigente y de dónde viene, por ejemplo "400 días, de la
configuración general". Un cambio en cualquier nivel llega al colector en unos segundos; las
señales que definen su propio valor no cambian. Cada cambio se escribe en el registro de
auditoría de PlantCraft.

## Agregaciones y el disco

Las tendencias de horas enteras, días o más, y el valor medio, más bajo y más alto de una
ventana, leen las agregaciones en lugar de todos los valores archivados: un año como tendencia
diaria lee 365 filas diarias. Las agregaciones tienen su propia retención, así que los valores
brutos pueden conservarse unos meses y los años de la planta se siguen viendo en tendencias, con
sus medias y extremos. Un nivel se conserva siempre al menos tanto como los valores brutos y los
niveles más finos (uno más corto solo se volvería a sumar a partir de ellos), y una señal
conservada para siempre conserva sus agregaciones para siempre.

**Disco por retención**, en la página Retención y recolección, muestra lo que guarda cada nivel
ahora y lo que guardará cuando cada señal conserve su retención completa, al ritmo de los valores
archivados en las últimas 24 h (por año para lo que se conserva para siempre). Una fila de
agregación horaria ocupa unos 125 bytes en disco, y una diaria o mensual, 150: un año de
agregaciones horarias de una señal son unos 1.1 MB, y de diarias, 55 KB.
