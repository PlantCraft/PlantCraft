# Como a suíte funciona

O PlantCraft fica no meio da suíte. Ele guarda as pessoas, as conexões de
dados e a árvore de ativos da planta; cada app da suíte roda ao lado dele, no
seu próprio contêiner, e lê o que precisa pela API v1.

```flow
Historiadores da planta | OPC UA, PI Web API ou CSV, só leitura
PlantCraft | Fontes, sinais, ativos, pessoas e acesso
API v1 | Tokens assinados, chaves de app e registro de auditoria
Apps da suíte | Link e os outros, cada um por conta própria
```

## O que fica onde

| O quê | Onde |
|---|---|
| Pessoas, senhas, níveis de acesso e apps por pessoa | PlantCraft |
| Fontes de dados, o cache de histórico e os sinais em uso | PlantCraft |
| Ativos, seus tipos e os sinais vinculados a eles | PlantCraft |
| Malhas (ativos do tipo `loop`, sinais por papel) | PlantCraft |
| Como cada malha é analisada, rodadas, notas e relatórios | Analytics |
| Quem alterou o quê, no PlantCraft e nos apps | Registro de auditoria do PlantCraft |

## Entrar uma vez

Você entra no PlantCraft. Ele dá ao seu navegador um token de curta duração
que cada app da suíte confere por conta própria, sem perguntar ao PlantCraft
a cada vez. Um app que não encontra o token manda você para o login do
PlantCraft e de volta. O trabalho que um app faz sozinho (as rodadas do
Analytics) usa uma chave de app que um administrador emite no PlantCraft.

## Só leitura

Nem o PlantCraft nem os apps escrevem na planta: as fontes são lidas, e o que
um app conclui é para as pessoas conferirem e decidirem.
