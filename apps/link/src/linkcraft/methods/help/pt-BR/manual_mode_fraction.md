# Modo manual

## O que detecta

A fração da janela em que o controlador não estava em automático, a partir do sinal de modo
(textos como `MAN` ou modos numéricos).

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. O tempo em manual
  é o primeiro indicador industrial de CPM: uma malha em manual não entrega nenhum de seus
  benefícios.

## Parâmetros

- `manual_labels` (padrão manual, man, m): os textos de modo (sem diferenciar maiúsculas) que
  significam operação manual; acrescente os rótulos do seu sistema (por exemplo, `cas` é
  automático, `lo` pode ser manual).
- `warning_fraction` (padrão 0.1): a fração da janela em manual em que a pontuação chega a 100; a
  pontuação é a fração em manual dividida por ela.

## Como ler o achado

"A malha ficou fora do automático em 35% do tempo." Isto é contexto, mostrado ao lado da
pontuação de saúde: comportamento do operador, não desempenho do controlador. Uma malha em manual
em metade da janela ou mais é marcada como inativa e não recebe pontuação de saúde. Operação
manual frequente costuma significar que os operadores não confiam na malha: olhe a sintonia, a
válvula e a medição.

## Limites

- A operação manual pode ser intencional (manutenção, partida, condições anormais).
- Precisa de um sinal de modo com rótulos confiáveis; modos numéricos contam como manual só quando
  seu valor está listado (`0` é lido como manual pela verificação do estado operacional).
