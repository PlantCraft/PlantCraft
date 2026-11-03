# Tempo na faixa de operação

## O que detecta

A fração da janela em que a PV fica dentro da faixa que a operação aceita (para um vaso pulmão,
entre seus níveis operacionais inferior e superior), e quanto do resto ficou abaixo ou acima.

Com limites definidos para a malha (`lower_limit` ou `upper_limit`), é um KPI simples de tempo
dentro dos limites e se aplica a qualquer malha. Com a faixa padrão de 20–80 ele se aplica só a
níveis pulmão: malhas cujo cadastro de ativo diz `level`, ou malhas no algoritmo de nível pulmão,
que define `assume_surge_level`. Nos demais casos retorna "não se aplica" com o motivo e fica fora
da saúde da malha (não conta como zero).

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. O tempo dentro dos
  limites operacionais é um KPI industrial comum.
- Jelali (2006), An overview of control performance assessment technology and industrial
  applications, Control Engineering Practice.
- Shinskey (1996), Process Control Systems: Application, Design and Tuning, McGraw-Hill, para a
  faixa do nível pulmão. A pontuação é a fração do tempo dentro da faixa.

## Parâmetros

- `lower_limit` (padrão 20): o limite inferior da faixa de operação, na unidade da PV.
- `upper_limit` (padrão 80): o limite superior da faixa de operação, na unidade da PV; precisa
  estar acima do limite inferior.
- `margin` (padrão 0): uma tolerância somada por fora dos dois limites antes que uma amostra conte
  como fora da faixa.
- `assume_surge_level` (padrão false): roda em uma malha cujo cadastro de ativo não informa o tipo;
  o algoritmo Nível pulmão o define, porque escolher esse algoritmo diz que a malha é um nível
  pulmão.

## Como ler o achado

"A PV ficou dentro da faixa de 20 a 80 em 97% do tempo (1% abaixo, 2% acima)." O desempenho é a
fração dentro da faixa e multiplica a saúde da malha. O tempo abaixo ou acima diz para que lado
olhar (uma válvula subdimensionada, uma perturbação que a malha não consegue rejeitar, uma faixa
definida apertada demais).

## Limites

- A faixa padrão de 20–80 supõe um nível pulmão em % da amplitude: defina os limites, na unidade
  da PV, para usar o bloco em qualquer outra malha.
- Os limites operacionais podem mudar com a taxa de produção ou a campanha.
