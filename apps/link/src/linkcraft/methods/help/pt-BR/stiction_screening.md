# Triagem de agarramento (stiction)

## O que detecta

O padrão de movimento de uma válvula de controle com agarramento (stiction): ela fica parada
enquanto o comando se move dentro da banda de agarramento, depois desliza em um salto, e a malha
cicla. A triagem lê a fração dos movimentos da saída que ficam parados e a fração de saltos logo
após um movimento parado (agarra e depois desliza), enquanto a PV oscila. Também lê a forma de uma
oscilação regular: uma válvula com agarramento faz a saída do controlador de uma malha
autorregulada (e a PV de um nível) ciclar em triângulos, enquanto uma sintonia agressiva ou uma
perturbação externa mantém os ciclos arredondados, como uma senoide. Quando a OP é a própria saída
do controlador, lê também a fase entre OP e PV (Horch): uma válvula com agarramento as desloca em
cerca de um quarto de ciclo, enquanto a sintonia ou uma perturbação as mantém em fase ou em
oposição de fase.

## Referência

- Choudhury, Thornhill e Shah (2005), Modelling valve stiction, Control Engineering Practice
  13(5): o modelo de banda de agarramento seguida de deslizamento que a triagem procura.
- Choudhury, Shah, Thornhill e Shook (2006), Automatic detection and quantification of stiction
  in control valves, Control Engineering Practice.
- He, Wang, Pottmann e Qin (2007), A curve fitting method for detecting valve stiction in
  oscillating control loops, Industrial & Engineering Chemistry Research 46(13): cada meio ciclo
  ajustado com uma senoide e com um triângulo; índice = erro da senoide / (erro da senoide + erro
  do triângulo).
- Horch (1999), A simple method for detection of stiction in control valves, Control Engineering
  Practice 7(10): a correlação cruzada entre a saída do controlador e a PV é ímpar sob agarramento
  e par sob efeito da sintonia ou de uma perturbação (malhas autorreguladas).
- Jelali e Huang (2010), Detection and Diagnosis of Stiction in Control Loops (Springer): a
  saturação é descartada antes de um teste de agarramento.
- Thornhill e Hägglund (1997): o teste de oscilação da PV (pico da autocorrelação).

## Parâmetros

- `movement_epsilon` (padrão 0.05): o maior movimento da saída, em %, que conta como parado.
- `jump_threshold` (padrão 0.5): o menor movimento da saída, em %, que conta como salto
  (deslizamento).
- `min_autocorrelation` (padrão 0.3): o pico da autocorrelação da PV em que a parte de oscilação
  da pontuação fica cheia.
- `min_lag_samples` (padrão 3): a menor defasagem, em amostras da grade, pesquisada para o pico da
  autocorrelação da PV.
- `jump_fraction_reference` (padrão 0.1): a fração de movimentos agarra-e-desliza em que a parte de
  deslizamento da pontuação fica cheia.
- `lower_limit` (padrão 0): o limite inferior da saída; os movimentos que o tocam ficam de fora.
- `upper_limit` (padrão 100): o limite superior da saída; os movimentos que o tocam ficam de fora.
- `margin` (padrão 1): quão perto de um limite uma amostra precisa estar para ficar de fora. Uma
  saída fora de `lower_limit`–`upper_limit` (um registro normalizado) não é verificada quanto aos
  limites.
- `shape_index_high` (padrão 0.65): o índice de ajuste de curva em que a parte de forma da
  pontuação fica cheia (0,5 é indeciso, 1 um triângulo puro).
- `min_half_cycles` (padrão 4): os meios ciclos regulares necessários antes que a forma seja
  julgada; meios ciclos cujas durações se espalham mais que a metade da média não são uma
  oscilação regular.
- `op_is` (padrão valve_command): o que a OP grava. Defina `controller_output` quando ela for a
  própria saída do controlador (a maioria dos registros de SDCD) para usar o teste de Horch; com um
  movimento de válvula gravado o teste não vale, porque a válvula também cicla em fase com a PV sob
  agarramento.
- `horch_even` (padrão 0.8): com `op_is` = `controller_output`, uma correlação cruzada na
  defasagem 0 de pelo menos esta fração do seu maior valor (um ciclo em fase ou em oposição de
  fase) deixa de fora a evidência de forma. A razão é sempre informada como `horch_index`.

## Como ler o achado

"Possível agarramento (stiction) da válvula: saída parada em 83% das amostras e saltando logo após
parar em 14%, com a PV oscilando. Isto é uma triagem; confirme em campo." Um diagnóstico fora da
pontuação de saúde: confirme com um teste de válvula (pequenos degraus da saída em manual), a
realimentação de posição ou um método completo de agarramento antes de planejar a manutenção.
"Agarramento (stiction) não triado: a saída ficou no limite" significa uma janela saturada, em que
o agarramento não pode ser visto.

## Limites

- A parte de agarra-e-desliza precisa de uma saída que mostre o movimento da válvula; a parte de
  forma precisa de uma oscilação regular ao longo de alguns ciclos da janela. O teste de Horch
  precisa da própria saída do controlador e de uma malha autorregulada (um nível se lê de outra
  forma). A elipse e a bicoerência não estão implementadas (lacuna G28).
- Outras causas (uma saída quantizada, um posicionador lento, banda morta) podem parecer
  semelhantes.
