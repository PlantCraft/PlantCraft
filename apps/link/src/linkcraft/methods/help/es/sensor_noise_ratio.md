# Ruido del sensor

## Qué detecta

Ruido de alta frecuencia en la medición: la dispersión de los cambios de muestra a muestra
(dividida por √2, el nivel de ruido del ruido blanco) comparada con la dispersión total de la PV,
y en términos absolutos. El ruido pasa por el controlador a la válvula y la desgasta.

## Referencia

- Bauer, Horch, Xie, Jelali y Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. La medida es una
  heurística de ingeniería.

## Parámetros

- `noise_ratio_threshold` (por defecto 0.35): la fracción de la variación de la PV atribuida al
  ruido en la que la parte de relación de la puntuación es completa (pesa 35%).
- `noise_abs_tolerance` (por defecto 0.5): la amplitud del ruido, en la unidad de la PV, en la que
  la parte absoluta de la puntuación llega a 100.

## Cómo leer el hallazgo

"El ruido de alta frecuencia es el 42% de la variación total de la medición." Un diagnóstico que
se muestra como alerta. Un ruido alto sugiere revisar el transmisor, su filtrado y la acción
derivativa; las mediciones de flujo son por naturaleza más ruidosas que las de temperatura.

## Límites

- Una dinámica rápida real del proceso parece ruido sin el contexto del proceso.
- En una grilla gruesa el promediado oculta el ruido; la tolerancia absoluta está en la unidad de
  la PV.
