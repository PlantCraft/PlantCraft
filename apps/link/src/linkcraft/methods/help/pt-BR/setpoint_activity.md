# Atividade do SP

## O que detecta

Com que frequência o setpoint se moveu mais que um limiar, em mudanças por hora, e o movimento
total. Movimentos frequentes do setpoint pelos operadores muitas vezes escondem uma malha que não
mantém o alvo sozinha.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. A pontuação é uma
  heurística de engenharia.

## Parâmetros

- `change_threshold` (padrão 0.1): o menor movimento do setpoint, na unidade da PV, contado como
  mudança.
- `max_changes_per_hour` (padrão 6): a taxa de mudanças por hora que pontua 100; a pontuação é a
  taxa dividida por ela. Malhas lentas (temperatura, composição) recebem uma taxa menor do seu tipo
  de malha.

## Como ler o achado

"14 mudanças de setpoint (0.6 por hora)." Uma taxa alta em uma malha cujo setpoint é definido por
pessoas diz que elas ficam corrigindo-a; no secundário de uma cascata ou em uma malha conduzida
por APC, é o esperado.

## Limites

- Receitas, transições e APC movem setpoints de propósito.
- O setpoint do secundário de uma cascata é escrito pelo primário a cada amostra: cada amostra
  conta como uma mudança.
