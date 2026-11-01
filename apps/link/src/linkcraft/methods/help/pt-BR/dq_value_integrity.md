# Integridade dos valores

## O que detecta

Se os valores da PV são confiáveis: a fração de amostras inválidas (texto, infinito, vazio, fora
dos limites físicos quando definidos) e o trecho mais longo em que a PV ficou exatamente constante
(um transmissor congelado). Faz parte do filtro de qualidade de dados.

## Referência

- Heurística de engenharia: um valor real de processo nunca fica exatamente constante por muito
  tempo; uma medição congelada ou inválida é descartada antes de julgar a malha, como em toda
  ferramenta de CPM que o levantamento (Bauer et al. 2016) cobre.

## Parâmetros

- `frozen_fraction_limit` (padrão 0.5): a maior fração da janela em que a PV pode ficar em um
  valor antes que os dados sejam rejeitados como congelados.
- `invalid_fraction_limit` (padrão 0.2): a maior fração de amostras inválidas antes que os dados
  sejam rejeitados.
- `lower_limit` (padrão none): o limite físico inferior da PV; valores abaixo dele são inválidos.
- `upper_limit` (padrão none): o limite físico superior da PV; valores acima dele são inválidos.

## Como ler o achado

"Os valores da PV são consistentes." ou "PV parada no mesmo valor em 100% da janela." Uma janela
rejeitada dá o estado "Dados não utilizáveis" e os métodos de CPM não rodam: verifique o
transmissor, sua comunicação e o sinal no PlantCraft.

## Limites

- Sinais calculados ou de baixa resolução, e analisadores que seguram o último valor, podem
  parecer congelados sem estar.
- Sem limites, valores fisicamente impossíveis não são detectados.
