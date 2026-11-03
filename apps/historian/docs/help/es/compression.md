# Compresión

Historian usa la compresión **swinging-door** (Bristol, 1990), el método de los historiadores de
esta categoría.

1. Cada valor leído se mantiene como el *snapshot*: las lecturas siempre lo incluyen, así que las
   tendencias llegan hasta el presente.
2. Un valor retenido se archiva solo cuando el siguiente valor muestra que una recta desde el
   último valor archivado ya no puede pasar dentro de la *desviación* de todos los valores leídos
   entre ambos.
3. Un valor se archiva al menos cada *intervalo máximo*, incluso en una señal plana.
4. Las señales de escalón y de texto archivan cada cambio, con el valor retenido justo antes de
   él, así que un escalón reconstruido es exacto.
5. Una calidad mala o una conexión perdida archiva una marca de hueco; el siguiente valor bueno
   empieza una nueva línea.
6. Un valor que se mantiene y luego salta más que la desviación se archiva en su última lectura
   antes del salto (una *marca de escalón*), así que la tendencia dibuja un escalón, no una rampa
   desde el último valor archivado.
7. Una señal numérica puede definir un *intervalo más corto entre valores archivados* (vacío:
   ninguno, como el CompMin de PI): un cambio más rápido se retiene hasta entonces, y la
   compresión continúa a partir de él. Los huecos, los cambios de calidad y las señales de
   escalón o de texto nunca se retienen.

Una tendencia reconstruida uniendo los valores archivados con rectas nunca se aleja más que la
desviación de ningún valor leído. Los promedios sobre una grilla son integrales exactas,
ponderadas en el tiempo, de esa tendencia reconstruida.
