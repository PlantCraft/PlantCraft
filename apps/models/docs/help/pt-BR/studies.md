# Estudos

Um **estudo** simula um modelo sobre uma grade de valores de parâmetros e compara as simulações:
qual tamanho de tanque mantém melhor o nível, quanta área de trocador de calor basta. Inicie um com
**Novo estudo** na página Estudos e escolha qualquer modelo, ou com **Novo estudo** na página de um
modelo, que abre a mesma página com esse modelo escolhido (`/studies/new`).

## Configurando

| Campo | Significado |
|---|---|
| Parâmetros | Cada parâmetro dos blocos do diagrama mantém o **Valor do modelo**, recebe um valor **Fixo** ou varia em uma **Faixa** (de, até, quantos valores, igualmente espaçados) ou em uma **Lista** de valores |
| Indicadores | Variáveis medidas em cada simulação; os sinais dos scopes vêm primeiro |
| Configurações da simulação | Início, fim, intervalos, tolerância e solver, a partir das configurações da simulação do modelo |
| Limite de tempo por simulação | Opcional, em minutos: uma simulação que demora mais é interrompida |

Cada combinação dos valores variados é uma simulação: 5 valores de `tank.A` e 3 de `tank.Cv` dão
15. A **Prévia** ao lado do formulário diz quantas serão antes de você começar, o que varia e
quanto tempo, aproximadamente, elas levam (a partir das últimas simulações deste modelo e do número
de workers). Acima de 100 ela avisa; um estudo tem no máximo 500 simulações, a menos que um
administrador altere `MODELCRAFT_STUDY_MAX_RUNS`.

O OpenModelica compila o modelo uma vez e depois só troca os parâmetros (o executor guarda o modelo
compilado para os próximos lotes do estudo, de até 10), então uma varredura custa bem menos que o
mesmo número de simulações separadas.

## Otimização: encontrar os melhores valores

Na página de novo estudo, **Encontrar os melhores valores** transforma o estudo em uma otimização:
em vez de todas as combinações, ela procura os valores de algumas entradas ou parâmetros que tornam
um indicador o melhor possível, uma simulação por vez, cada uma escolhida a partir dos resultados
das anteriores.

| Campo | Significado |
|---|---|
| Otimizar | Na tabela de parâmetros, uma entrada ou parâmetro marcado como **Otimizar** recebe seu **menor** e seu **maior** valor e, opcionalmente, onde o otimizador **começa** (o meio dos limites quando vazio). Até 10 |
| Objetivo | Uma variável e um dos indicadores dela (valor final, sobressinal, tempo de acomodação, IAE, ...), para **Minimizar**, **Maximizar** ou **Atingir um valor** (a distância ao quadrado até o alvo é minimizada) |
| Restrições | Opcional: outros indicadores mantidos abaixo ou acima de um limite (`tank.level` maior ≤ 2.5). Até 10 |
| Método | **Automático** usa Nelder-Mead, ou COBYLA quando há restrições. **Nelder-Mead** (sem derivadas, sem restrições), **COBYLA** (sem derivadas, com restrições), **SLSQP** (gradientes por diferenças finitas, com restrições; menos simulações em problemas suaves, mas cada passo custa uma simulação por valor) |
| Máximo de simulações | O otimizador para quando os melhores valores não mudam mais, ou aqui (60 por padrão) |

Os métodos são os do SciPy (`scipy.optimize.minimize`). Os valores são escalados para 0..1 entre
seus limites, então os primeiros passos (um quarto de cada faixa) servem para qualquer unidade. Uma
simulação que falha custa ao otimizador um valor muito grande, então ele se afasta dela. A melhor
simulação é a que tem o melhor objetivo entre as que atendem a todas as restrições; quando nenhuma
atende, a que mais se aproxima de atendê-las, e a página avisa isso.

A página do estudo abre com o painel **Otimização**: como ela está indo, os melhores valores ao
lado do início e dos limites deles, um link para a melhor simulação e um gráfico do objetivo de cada
simulação (as que não atendem a uma restrição em outra cor) com o melhor até agora. O restante da
página se lê como o de qualquer estudo: cada simulação que o otimizador pediu está em
**Simulações**, com os valores dela.

Toda instalação tem um exemplo: **Example: tune the PI for the least IAE** altera o controlador PI
de `FirstOrderDeadTimeLoop` (ganho `controller.k` de 0.1 a 4, tempo integral `controller.Ti` de 2 a
100 s, começando lento em 0.4 e 60 s) para tornar mínimo o IAE da medição `dead_time.y`, com
sobressinal de no máximo 10 % (COBYLA). Ele termina perto de k 1.2 e Ti 21 s. O IAE é medido a
partir do valor final da variável, então deixe a simulação rodar até a malha se acomodar (aqui,
300 s). Para sintonizar uma malha sua, coloque o modelo do processo dela na frente de um bloco PID e
faça o mesmo.

As otimizações são sequenciais (cada ponto depende do anterior): cerca de 20 a 60 simulações para
dois ou três valores. O executor compila o modelo na primeira e o guarda, então cada passo seguinte
só o roda (cerca de um segundo cada para os exemplos). Se o PlantCraft reiniciar durante uma, ela
continua sozinha na próxima inicialização: o otimizador pede os mesmos pontos de novo e as
simulações que ele já tem respondem na hora. **Cancelar o restante** a interrompe.

## Lendo um estudo

- **Classificação** ordena as simulações por um indicador e uma estatística: valor final, menor,
  maior, média, integral, **sobressinal** (quanto passou do valor final, em %), **tempo de
  acomodação** (quando entrou pela última vez na faixa de 2 % em torno do valor final) e **IAE** (a
  integral do erro absoluto em relação ao valor final). **Melhor é** diz se ganha o menor ou o
  maior; a melhor simulação é destacada e indicada acima da tabela. Clique em uma simulação para
  abri-la.
- **Resultados** sobrepõe uma variável de todas as simulações concluídas. **Colorir por** um
  parâmetro variado sombreia as linhas do claro (menor valor) ao escuro (maior); **Envoltória**
  desenha a faixa onde caem 90 % das simulações e a mediana delas. **Indicador contra um
  parâmetro** plota um indicador de cada simulação contra um parâmetro variado.
- **Simulações** lista as simulações com os valores que cada uma usou. Marque algumas e clique em
  **Comparar estas** para sobrepor só essas.
- **Estatísticas sobre as simulações** dá, para cada indicador, a média, o desvio padrão e os
  percentis sobre as simulações.
- **Lado a lado** desenha um gráfico pequeno por valor de um parâmetro variado, todos na mesma
  escala vertical, para que as saídas de cada escolha fiquem uma ao lado da outra; dentro de cada
  gráfico, as linhas são sombreadas pelo outro parâmetro variado.
- **Simular de novo com alterações** abre a página de novo estudo com as mesmas configurações.

**Cancelar o restante** interrompe as simulações em andamento do estudo e tira da fila as que
esperam. Uma simulação que falha (um valor de parâmetro que o modelo não aceita) é marcada como
falha; as outras continuam.

## Exportar para Jupyter

**Exportar para Jupyter** baixa um .zip com:

| Arquivo | O que é |
|---|---|
| `parameters.csv` | Uma linha por simulação: o id, os valores e os indicadores dela |
| `results.csv` | Todos os pontos de todas as simulações concluídas: `run_id`, `time` e as variáveis |
| `study.ipynb` | Um notebook que lê os dois com pandas e plota os indicadores |
| `study.json` | As configurações do estudo |
| `model/` | Os arquivos Modelica do modelo como estavam |

Abra-o no Jupyter, no JupyterLab ou no VS Code. O notebook só precisa de pandas e matplotlib.
