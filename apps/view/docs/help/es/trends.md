# Tendencias

**Tendencias** dibuja señales sobre un período en un gráfico o en subgráficos apilados que
comparten el eje de tiempo. Guarde una tendencia para abrirla de nuevo, o descargue lo que muestra
como CSV.

- **Período**: de los últimos 15 minutos a 30 días, o un "desde – hasta" fijo.
- **Intervalo**: cuánto tiempo abarca cada valor dibujado. "Automático" lo elige a partir del
  período (unos 600 valores por línea); "Como se registró" dibuja cada muestra.
- Agregue señales a un gráfico con la búsqueda debajo de él; hasta 8 líneas por gráfico y 6
  gráficos.
- **Comparar con**: dibuja hasta tres períodos anteriores sobre el de la tendencia, cada línea
  punteada y más clara en el color de su línea, y con el nombre de su período: el **período
  anterior** (justo antes, tan largo como el de la tendencia), **1 día antes** (ayer sobre hoy),
  **1 semana antes** o **4 semanas antes**. Cada período anterior se lee con el intervalo de la
  tendencia y se desplaza sobre su eje de tiempo, así que al pasar el cursor se ve la hora de hoy;
  el nombre de la línea dice qué período es. Los estados (señales de texto) no se comparan. Se
  guarda con la tendencia.

## Cada línea

Haga clic en el nombre de una línea para configurarla por separado, aparte de las demás líneas:

- **Intervalo**: el de la tendencia (el predeterminado) o el propio de la línea, de 1 minuto a
  1 día o como se registró. La PV cada minuto junto al SP cada hora en el mismo gráfico son dos
  líneas con dos intervalos.
- **Cada intervalo muestra**: la media (la predeterminada), el último valor, el primer valor, el
  mínimo o el máximo de cada intervalo. La misma señal se puede dibujar dos veces, por ejemplo su
  media y su máximo. Los resúmenes distintos de la media leen las muestras como se registraron;
  sobre un período muy largo con demasiadas muestras la línea vuelve a la media y lo indica debajo
  del gráfico.
- **Dibujar como**: una línea, puntos o ambos; entre muestras recto, en escalones (cada valor se
  mantiene hasta el siguiente, como lo ve un controlador) o suave.
- **Color** (automático o elegido), **trazo**, **grosor de línea** y **tamaño del punto**.
- **Eje Y**: izquierdo, o derecho con su propia escala, para comparar señales de rangos distintos
  en el mismo gráfico.

El CSV tiene una columna por línea dibujada, nombrada con su resumen cuando no es la media.

## El gráfico

- Un eje nombra su unidad solo cuando todas sus líneas tienen la misma; con dos unidades la
  leyenda y la información al pasar el cursor siguen dando a cada línea la suya.
- **Pantalla completa**, arriba a la izquierda del gráfico, muestra solo el gráfico; Esc sale.
- **Gráfico**: "Como la plataforma" sigue su tema; **Claro** u **Oscuro** fija los colores del
  gráfico, incluida la imagen, sea cual sea el tema de la plataforma. La elección se queda en este
  navegador.
- Los botones de Plotly, arriba a la derecha del gráfico, acercan, desplazan y descargan el
  gráfico como un PNG con el nombre de la tendencia.
