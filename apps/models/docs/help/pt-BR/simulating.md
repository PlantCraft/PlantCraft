# Simulando

**Simular**, na página de um modelo, salva o diagrama e o simula com as **Configurações da
simulação** dele:

| Configuração | Significado |
|---|---|
| Início, Fim | O período simulado, em segundos de tempo do modelo |
| Solver | Como as equações são integradas no tempo (abaixo) |
| Passo | Com um solver de passo fixo, o passo de integração; com um de passo variável, o passo de saída (um ponto de resultado por passo) |
| Tolerância | A tolerância relativa de um solver de passo variável |

| Solver | Quando |
|---|---|
| DASSL (o padrão), IDA | BDF de passo variável: sistemas rígidos e a maioria dos modelos de processo |
| CVODE | Passo variável: sistemas suaves |
| Euler, Heun, Runge-Kutta | Passo fixo, explícito: sistemas não rígidos |
| Euler implícito, Trapézio | Passo fixo, implícito: sistemas rígidos com passo fixo |

Uma simulação tem no máximo 200 000 passos. As configurações são salvas com o modelo (a anotação
`experiment` dele), então toda simulação e todo estudo partem delas.

Um modelo roda quando toda entrada de todo bloco tem uma ligação; o diagrama marca o que falta.
Malhas de realimentação (um controlador que lê o nível que ele mesmo move) são permitidas.

## Os resultados

Os resultados abaixo do diagrama plotam o que os **scopes** do modelo mostram. Abra a simulação
para ver a página própria dela:

- as variáveis escolhidas à esquerda (até 12); **Principal** esconde as derivadas e as variáveis
  protegidas, **Todos** mostra todas; cada uma mostra seu valor final;
- **Comparar com** desenha as mesmas variáveis de outra simulação do mesmo modelo, tracejadas;
- **Resultados em CSV** baixa todas as variáveis em todos os pontos;
- **Mensagens** lista o que o OpenModelica e o solver disseram.

Uma simulação que falha é marcada como **Falhou**, e as mensagens dela dizem por quê: uma equação
que não pôde ser resolvida, uma divisão por zero, um passo grande demais para o solver.

## Simulações e a fila

**Simulações** é organizada como os Resultados do Analytics, com o estudo no lugar do monitor e a
simulação no lugar do ativo. **Por estudo** lista cada estudo (e as **simulações avulsas** de cada
modelo, o que Simular inicia) com o que ele varia e como as simulações terminaram; abra um para ver
um resumo e as simulações dele, e uma simulação para ver os resultados. **Fila** mostra o que roda
e o que espera, agora e ao longo do tempo (o mesmo painel de todos os apps da suíte), e depois todas
as simulações. Duas simulações rodam ao mesmo tempo por padrão (um administrador define
`MODELCRAFT_RUN_WORKERS`); as simulações avulsas passam à frente dos estudos, então um estudo longo
nunca bloqueia uma verificação rápida. Uma simulação para depois do seu limite de tempo (no máximo
6 horas, `MODELCRAFT_MAX_RUN_SECONDS`).
