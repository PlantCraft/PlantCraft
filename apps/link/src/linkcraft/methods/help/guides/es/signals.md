# Señales

Todas las señales que conoce PlantCraft, con su resultado más reciente del algoritmo Calidad de la
señal. Filtre por estado, por fuente, por una verificación que la señaló, o busque por id y
nombre. Abra una señal para ver por qué recibió su resultado.

- **Bueno** (se muestra en PlantCraft como *OK*): todas las verificaciones aprobaron.
- **Sospechoso** (*Advertencia*): al menos una verificación advirtió; los datos todavía son
  utilizables.
- **Malo** (*Alarma*): al menos una verificación falló; los lazos y las otras apps no deberían
  confiar en estos datos.
- **Desconocido**: ninguna verificación pudo juzgar la señal (muy pocas muestras, ilegible, solo
  texto).

La calidad es 100 menos la puntuación de la peor verificación: 100 es perfecta, por debajo de 25
no es utilizable.

Las señales vienen del catálogo de PlantCraft a través de la API v1; Analytics nunca mantiene su
propia lista de tags. Las señales derivadas (series que calculó una app, como las puntuaciones
propias de calidad y salud de Analytics) no se verifican. Una señal que desaparece de PlantCraft se
marca como faltante y se conserva, para que su historial permanezca.
