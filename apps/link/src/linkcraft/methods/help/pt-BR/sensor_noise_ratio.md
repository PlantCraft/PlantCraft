# Ruído do sensor

## O que detecta

Ruído de alta frequência na medição: a dispersão das variações de uma amostra para a seguinte
(dividida por √2, o nível de ruído de um ruído branco) comparada com a dispersão total da PV, e em
termos absolutos. O ruído passa pelo controlador até a válvula e a desgasta.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. A medida é uma
  heurística de engenharia.

## Parâmetros

- `noise_ratio_threshold` (padrão 0.35): a fração da variação da PV atribuída ao ruído em que a
  parte de razão da pontuação fica cheia (ela pesa 35%).
- `noise_abs_tolerance` (padrão 0.5): a amplitude do ruído, na unidade da PV, em que a parte
  absoluta da pontuação chega a 100.

## Como ler o achado

"O ruído de alta frequência é 42% da variação total da medição." Um diagnóstico mostrado como
alerta. Ruído alto sugere verificar o transmissor, sua filtragem e a ação derivativa; medições de
vazão são naturalmente mais ruidosas que as de temperatura.

## Limites

- Dinâmicas de processo reais e rápidas parecem ruído sem o contexto do processo.
- Em uma grade grosseira a média esconde o ruído; a tolerância absoluta está na unidade da PV.
