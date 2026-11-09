# Deriva da saída

## O que detecta

A saída do controlador andando sempre para o mesmo lado, hora após hora, enquanto a PV segura o
setpoint. Um transmissor com deriva faz o controlador segurar a leitura errada: a PV parece
perfeita enquanto o processo se afasta, e o único rastro nos dados da malha é a saída seguindo a
deriva. Incrustação, uma válvula se desgastando ou uma carga que muda devagar deixam o mesmo
rastro.

A janela é dividida em blocos (uma hora por padrão); a deriva é a variação mediana da mediana da
saída de um bloco para o seguinte, contada só entre blocos em que o setpoint ficou parado, para
que um degrau isolado (uma calibração, uma troca de setpoint) não conte. Ela pontua quando a
maioria das variações vai para o mesmo lado.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. A medida é uma
  heurística de engenharia.

## Parâmetros

- `block_minutes` (padrão 60): a duração dos blocos cuja saída mediana é comparada.
- `drift_per_day` (padrão 6): a deriva, em % da OP por dia, que pontua 100.
- `min_consistency` (padrão 0.6): a fração das variações entre blocos no sentido da deriva a
  partir da qual ela conta.
- `full_consistency` (padrão 0.8): a fração em que ela conta por inteiro.
- `min_blocks` (padrão 8): o menor número de blocos com setpoint parado para julgar.

## Como ler o achado

"A saída deriva para baixo cerca de 7 % por dia (91% das variações entre blocos no mesmo sentido)
enquanto o setpoint fica parado: um transmissor com deriva, incrustação ou uma carga que muda
devagar." Um diagnóstico mostrado como alerta, fora da nota. Compare a PV com uma medição
redundante, um resultado de laboratório ou um balanço: um transmissor com deriva precisa de
calibração. Se ele lê certo, procure incrustação, desgaste da válvula ou uma carga que muda
devagar.

## Limites

- Não distingue um transmissor com deriva de uma mudança lenta do processo: confirme em campo.
- Uma deriva calibrada de volta dentro da janela, ou mais lenta que ela, aparece mais fraca.
- Uma malha cujo setpoint muda toda hora tem poucos blocos parados para julgar (sem resultado).
