# Oscilação

## O que detecta

Uma oscilação sustentada e regular da malha: do erro de controle (PV − SP) quando o setpoint é
conhecido, senão da PV. A oscilação é o problema de desempenho mais comum das malhas industriais,
causado por sintonia agressiva, uma válvula com agarramento ou uma perturbação oscilante vinda de
outra malha.

## Referência

- Thornhill e Hägglund (1997), Detection and diagnosis of oscillation in control loops, Control
  Engineering Practice: a oscilação aparece como um pico nítido da função de autocorrelação (ACF)
  depois da defasagem zero.
- Thornhill, Huang e Zhang (2003), Detection of multiple oscillations in control loops, Journal
  of Process Control 13(1): a regularidade r = período médio / (3 × desvio padrão dos períodos
  entre cruzamentos alternados da ACF por zero); a oscilação é regular quando r > 1.

## Parâmetros

- `min_lag_samples` (padrão 3): a menor defasagem da ACF, em amostras da grade da análise,
  pesquisada para o pico; define o menor período que pode ser visto.
- `max_lag_samples` (padrão none): a maior defasagem pesquisada; none usa a janela inteira.
- `min_cycles` (padrão 3): o número de ciclos que a janela precisa conter para a pontuação ser
  cheia; um período longo demais para a janela reduz a pontuação.
- `min_autocorrelation` (padrão 0.3): o pico da ACF a partir do qual uma repetição conta como
  oscilação.
- `min_regularity` (padrão 1): a regularidade r a partir da qual a oscilação conta como sustentada
  (Thornhill, Huang e Zhang usam 1).

## Como ler o achado

"Oscilação com período de cerca de 5 min, 72 ciclos na janela (autocorrelação 0.89, regularidade
100)." É um diagnóstico mostrado como alerta, não parte do produto da saúde. O período ajuda a
achar a causa: um período próximo do tempo de resposta da própria malha aponta para a sintonia ou
a válvula; o mesmo período em várias malhas aponta para uma fonte única se espalhando pela planta
(veja Interação entre malhas). "Nenhuma oscilação sustentada ... o período é irregular" significa
uma perturbação isolada ou um degrau de setpoint, não um ciclo.

## Limites

- Uma triagem: não distingue uma oscilação causada pela sintonia de uma causada por uma
  perturbação externa (lacuna G29) ou por agarramento (veja Triagem de agarramento).
- Períodos mais curtos que cerca de três amostras da grade (3 min na grade padrão de 60 s) não
  podem ser vistos.
- Uma oscilação cujo período deriva muito na janela não é regular e não é sinalizada.
