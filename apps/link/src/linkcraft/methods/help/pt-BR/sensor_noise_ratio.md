# Ruído do sensor

## O que detecta

Ruído na medição, julgado na escala da própria malha: o ruído de uma amostra para a seguinte,
estimado pelas segundas diferenças da PV (com o desvio absoluto mediano, para que degraus de
setpoint e mudanças de carga não contem), como fração da faixa da PV ou, sem ela, do tamanho do
setpoint. O ruído passa pelo controlador até a válvula, a desgasta e esconde o que a malha faz.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. A medida é uma
  heurística de engenharia.

## Parâmetros

- `relative_noise_percent` (padrão 2): o ruído, em percentual da escala da malha, que pontua 100
  (o pior); alerta a partir de um quarto disso.
- `noise_ratio_threshold` (padrão 0.35): a fração da variação da PV explicada pelo ruído em que o
  ruído pesa por inteiro. Uma PV que oscila ou se move muito tem a maior parte da variação fora do
  ruído, e seus movimentos de amostra a amostra são o ciclo mais que ruído: a pontuação cai.
- `noise_abs_tolerance` (padrão nenhum): um ruído absoluto, na unidade da PV, que pontua 100.
  Vazio: uma fração da escala da malha.
- `pv_span` (padrão nenhum): a faixa de engenharia da PV; vazio, a escala é a mediana de |SP| (ou
  de |PV| sem setpoint).

## Como ler o achado

"Ruído de amostra a amostra de 1,3 (2,6 % da escala da malha), 95% da variação da medição." Um
diagnóstico mostrado como alerta, fora da nota. Ruído acima de cerca de 0,5 % da escala numa malha
justa merece uma olhada no transmissor, nas tomadas de impulso, na filtragem e na ação
derivativa; analisadores são naturalmente mais ruidosos que temperaturas.

## Limites

- Um processo mais rápido que a amostragem (uma vazão rápida amostrada uma vez por minuto) parece
  ruído.
- Em uma grade grosseira a média esconde o ruído.
- Uma PV mantida perto de zero deixa a tolerância relativa apertada: dê à malha seu `pv_span` ou
  um `noise_abs_tolerance` absoluto.
