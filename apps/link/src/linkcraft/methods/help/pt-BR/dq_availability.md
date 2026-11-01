# Disponibilidade do sinal

## O que detecta

Se os sinais da malha foram gravados ao longo da janela: para cada sinal, a cobertura (1 − o
tempo perdido em lacunas mais longas que um intervalo máximo, sobre a janela) e a maior lacuna.
Faz parte do filtro de qualidade de dados: se a PV cobre pouco da janela, os métodos de CPM não
rodam.

## Referência

- Heurística de engenharia. Historiadores com compressão gravam só as mudanças, então um intervalo
  até o máximo configurado ainda conta como dado válido; a triagem dos dados antes de qualquer
  julgamento é o primeiro passo que o levantamento de CPM (Bauer et al. 2016) descreve.

## Parâmetros

- `max_gap_seconds` (padrão 600): o maior intervalo, em segundos, entre duas amostras gravadas que
  ainda conta como dado; o tempo além dele é uma lacuna. Malhas lentas (temperatura, composição)
  recebem um intervalo maior do seu tipo de malha.
- `min_coverage` (padrão 0.8): a cobertura da PV abaixo da qual os dados não são utilizáveis e os
  métodos de CPM não rodam.

## Como ler o achado

"A PV cobre 97% da janela." Quando diz "A PV cobre só 40% da janela (mínimo 80%)", o estado da
malha é "Dados não utilizáveis" e nenhuma pontuação de desempenho é dada: corrija primeiro o
caminho dos dados (conexão com a fonte, historiador, mapeamento do sinal no PlantCraft).

## Limites

- Verifica que os valores existem, não que estão certos (veja Integridade dos valores).
- Não distingue uma falha de comunicação de um equipamento parado.
