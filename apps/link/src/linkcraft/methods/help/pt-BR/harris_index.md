# Índice de variância mínima

## O que detecta

Quanto a variância da malha está acima da menor variância que qualquer controlador conseguiria
com o tempo morto da malha: o índice de variância mínima (Harris). É a referência clássica da
avaliação de desempenho de malhas de controle e precisa só de dados de operação de rotina, sem
teste de degrau.

## Referência

- Harris (1989), Assessment of control loop performance, The Canadian Journal of Chemical
  Engineering 67(5): a parte do erro que cai dentro do tempo morto não pode ser removida pela
  realimentação, então sua variância é a referência de variância mínima; o índice é essa
  referência sobre a variância real.
- Horch e Isaksson (1999), A modified index for control performance assessment, Journal of
  Process Control 9(6): por que o limite de variância mínima muitas vezes está fora de alcance na
  prática e um índice bem abaixo de 1 ainda pode ser uma boa malha.
- Bauer et al. (2016), The current state of control loop performance monitoring, Journal of
  Process Control: o uso do índice e suas armadilhas na indústria.

## Parâmetros

- `dead_time_seconds` (padrão 0): o tempo morto da malha; 0 o estima como a defasagem, em
  amostras, da maior correlação cruzada entre os movimentos da OP e os da PV (uma amostra quando
  não há OP).
- `ar_order` (padrão 20): a ordem do modelo autorregressivo ajustado ao erro de controle; é elevada
  ao tempo morto mais um quando o tempo morto é maior.
- `max_delay_samples` (padrão 60): o maior tempo morto, em amostras, procurado quando é estimado a
  partir da OP e da PV.
- `good_index` (padrão 0.5): o índice a partir do qual a malha pontua como saudável; malhas
  industriais bem sintonizadas costumam ficar entre 0,3 e 0,6.
- `poor_index` (padrão 0.1): o índice igual ou abaixo do qual a pontuação é 100; a pontuação cai
  linearmente entre os dois.

## Como ler o achado

"A variância é 4.2 vezes a referência de variância mínima (tempo morto de 7 amostras): uma nova
sintonia poderia remover até 76% dela." Um índice perto de 1 significa que a malha já rejeita
perturbações quase tão bem quanto a realimentação permite; um índice baixo aponta para controle
lento ou oscilante, em que uma nova sintonia, um reparo de válvula ou um feedforward podem
compensar. Confira o tempo morto usado (`delay_source`: parâmetro, estimado ou assumido): um
estimado ou assumido deve ser confirmado antes de agir.

## Limites

- A variância mínima é um limite teórico que costuma exigir controle agressivo e grandes
  movimentos da OP; o índice diz quanto poderia ser ganho, não que deva ser.
- Um tempo morto errado desloca o índice: um mais curto faz a malha parecer pior.
- Mudanças de setpoint, saturação e modo manual na janela o distorcem; ele não faz parte dos
  algoritmos fornecidos e é adicionado a um algoritmo quando desejado.
