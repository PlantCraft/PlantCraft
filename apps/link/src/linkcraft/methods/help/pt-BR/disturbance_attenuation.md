# Atenuação de perturbações

## O que detecta

Se uma malha de nível de média (nível pulmão) cumpre seu papel: absorver no vaso as perturbações
da vazão de entrada e passar adiante uma vazão de saída suave. Compara quanto a saída do
controlador percorre com quanto o nível percorre, ambos normalizados pelas suas faixas. Uma saída
que se move mais que o nível repassa as perturbações para jusante em vez de usar a capacidade do
vaso.

Aplica-se só a níveis pulmão: malhas cujo cadastro de ativo diz `level`, ou malhas no algoritmo
de nível pulmão, que define `assume_surge_level`. Em uma malha de vazão, pressão, temperatura ou
composição, ou em uma malha cujo cadastro não informa o tipo, retorna "não se aplica" com o motivo
e fica fora da saúde da malha (não conta como zero).

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. O controle de
  nível de média é julgado pela vazão de saída que repassa, não pelo rastreamento do setpoint.
- Shinskey (1996), Process Control Systems: Application, Design and Tuning, McGraw-Hill.
  Tratamento clássico do controle de nível de média: o vaso absorve as perturbações para que a
  vazão de saída fique suave. A razão de amplificação e seus limiares são uma heurística de
  engenharia construída sobre essa ideia; ajuste-os por planta.

## Parâmetros

- `pv_range` (padrão 100): a faixa da PV usada para normalizar seu curso (100 para um nível em %).
- `op_range` (padrão 100): a faixa da saída usada para normalizar seu curso (100 para uma saída em %).
- `full_performance_factor` (padrão 0.5): a amplificação (curso normalizado da OP sobre curso
  normalizado da PV) que pontua 100%: a vazão de saída se move metade do que o nível se move.
- `zero_performance_factor` (padrão 1.5): a amplificação que pontua 0%; entre os dois o
  desempenho cai linearmente.
- `movement_epsilon` (padrão 0.01): o menor curso normalizado da PV necessário para uma razão
  estável; abaixo dele o método informa dados insuficientes (um nível que não se moveu).
- `assume_surge_level` (padrão false): roda em uma malha cujo cadastro de ativo não informa o tipo;
  o algoritmo Nível pulmão o define, porque escolher esse algoritmo diz que a malha é um nível
  pulmão.

## Como ler o achado

"A saída se move 1.8 o movimento normalizado da PV: o controle repassa as perturbações em vez de
absorvê-las no nível." Um fator abaixo de 1 é o que um nível de média deve fazer; acima de 1 o
nível está sendo segurado com força demais (sintonia agressiva demais para média) e as unidades a
jusante sentem as perturbações.

## Limites

- Só para controle de nível de média; em uma malha de nível apertado um fator alto é intencional.
  Um nível cujo cadastro diz `level` mas que é controlado de forma apertada precisa de outro
  algoritmo.
- Faixas de PV ou de OP erradas tornam a razão sem sentido.
- Um nível que quase não se move não dá uma razão estável.
