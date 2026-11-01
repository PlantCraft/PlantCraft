# Cómo funciona la suite

PlantCraft está en el medio de la suite. Guarda las personas, las conexiones de
datos y el árbol de activos de la planta; cada app de la suite se ejecuta a su
lado, en su propio contenedor, y lee lo que necesita a través de la API v1.

```flow
Historiadores de la planta | OPC UA, PI Web API o CSV, solo lectura
PlantCraft | Fuentes, señales, activos, personas y acceso
API v1 | Tokens firmados, claves de las apps y registro de auditoría
Apps de la suite | Link y las demás, cada una por su cuenta
```

## Qué vive dónde

| Qué | Dónde |
|---|---|
| Personas, contraseñas, niveles de acceso y apps por persona | PlantCraft |
| Fuentes de datos, la caché del histórico y las señales en uso | PlantCraft |
| Activos, sus tipos y las señales vinculadas a ellos | PlantCraft |
| Lazos (activos de tipo `loop`, señales por rol) | PlantCraft |
| Cómo se analiza cada lazo, rondas, puntuaciones e informes | Analytics |
| Quién cambió qué, en PlantCraft y en las apps | Registro de auditoría de PlantCraft |

## Iniciar sesión una sola vez

Usted inicia sesión en PlantCraft. PlantCraft le da a su navegador un token de
corta duración que cada app de la suite verifica por su cuenta, sin consultar a
PlantCraft cada vez. Una app que no encuentra un token lo envía al inicio de
sesión de PlantCraft y de vuelta. El trabajo que una app hace por su cuenta (las
rondas de Analytics) usa una clave de app que un administrador emite en
PlantCraft.

## Solo lectura

Ni PlantCraft ni las apps escriben en la planta: las fuentes se leen, y lo que
una app concluya queda para que las personas lo verifiquen y decidan.
