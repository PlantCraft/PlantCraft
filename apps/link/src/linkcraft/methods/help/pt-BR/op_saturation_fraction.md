# Saturação da saída

## O que detecta

A fração da janela em que a saída do controlador ficou em (ou perto de) um de seus limites. Uma
saída saturada significa que o controlador ficou sem autoridade: a válvula está totalmente aberta
ou fechada e a malha está, na prática, aberta.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. A saturação é um
  dos indicadores básicos que o levantamento lista; a pontuação é uma heurística de engenharia.

## Parâmetros

- `lower_limit` (padrão 0): o limite inferior da saída, na sua unidade (0 para uma saída em %).
- `upper_limit` (padrão 100): o limite superior da saída (100 para uma saída em %).
- `margin` (padrão 1): quão perto de um limite uma amostra precisa estar para contar como saturada.
- `warning_fraction` (padrão 0.05): a fração saturada em que a pontuação chega a 100; a pontuação
  é a fração saturada dividida por ela.

## Como ler o achado

"A saída do controlador ficou nos limites em 93% do tempo." O desempenho (100% menos a fração
saturada) multiplica a saúde da malha. Uma saída saturada com a PV longe do setpoint significa que
a válvula, a bomba ou o setpoint não servem para o serviço (válvula subdimensionada, trocador
incrustado, um setpoint que o processo não consegue alcançar). O agarramento (stiction) não pode
ser triado enquanto a saída está em um limite.

## Limites

- A saturação pode ser uma restrição do processo (um seletor, um limite de projeto) em vez de uma
  falha.
- Limites de saída diferentes de 0–100 precisam ser configurados.
