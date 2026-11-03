# Resumen

La página de resumen indica si Historian está recolectando y cuánto guarda.

- **Colector**: en ejecución o detenido, con la hora de su último latido. Historian archiva un
  hueco para cada señal cuando el colector se detiene, así que las tendencias nunca trazan una
  línea a través de una parada.
- **Señales**: cuántas están recolectando, en espera, fallando o deshabilitadas.
- **Archivo histórico**: valores archivados, bytes en disco y la relación de compresión (valores
  leídos por valor conservado).
- **Fuentes**: cada servidor OPC UA, su estado y su último error.
