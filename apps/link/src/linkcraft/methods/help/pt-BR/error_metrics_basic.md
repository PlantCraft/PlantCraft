# Erro PV–SP

## O que detecta

Quanto a variável de processo fica longe do setpoint ao longo da janela: o erro absoluto médio
(MAE), o RMSE, a integral do erro absoluto (IAE), do erro quadrático (ISE) e do erro absoluto
ponderado pelo tempo (ITAE), e a fração do tempo em que a PV fica dentro de uma faixa aceitável
em torno do setpoint. É a medida básica de rastreamento de uma malha que precisa manter ou seguir
o setpoint.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. As integrais de
  erro são as medidas de desempenho mais usadas nas ferramentas industriais que o levantamento
  cobre, que classificam toda a população de malhas de uma planta por esses KPIs. Um erro na
  própria unidade da PV não pode ser comparado entre malhas (um erro médio de 1 é nada para uma
  vazão de 500 t/h e muito para 2 bar), então o erro é pontuado contra uma fração da escala de cada
  malha. O padrão de 4 % é uma heurística de engenharia, não uma referência de um artigo.

## Parâmetros

- `error_tolerance` (padrão none): um erro absoluto médio absoluto, na unidade da PV, que pontua
  100 (o pior). Vazio: a tolerância é `relative_tolerance_percent` da escala da malha. Um algoritmo
  ou malha que o define o usa como informado.
- `acceptable_band` (padrão none): uma meia largura absoluta, na unidade da PV, da faixa em torno
  do setpoint que conta como no alvo. Vazio: `relative_band_percent` da escala.
- `relative_tolerance_percent` (padrão 4): o erro absoluto médio que pontua 100, em percentual da
  escala da malha; um erro de 1 % da escala custa 25 pontos.
- `relative_band_percent` (padrão 1): a faixa no alvo, em percentual da escala da malha.
- `pv_span` (padrão none): a amplitude de engenharia da PV. Quando informada, é a escala da malha;
  vazia, a escala é o tamanho do setpoint (mediana de |SP|) ao longo da janela.

## Como ler o achado

"Erro absoluto médio PV–SP de 0.8; a PV ficou dentro de ±0.5 do setpoint em 64% do tempo."
O resultado também dá a tolerância usada, a escala e sua base (`pv_span`, `setpoint`, ou
`absolute` quando uma tolerância foi informada ou o setpoint fica em zero).
O desempenho mostrado é 100 menos a pontuação, então 100% significa nenhum erro e 0% um erro igual
ou acima da tolerância; ele multiplica a saúde da malha. Um erro grande com a saída travada aponta
para saturação (veja Saturação da saída); com a PV ciclando, para oscilação; com movimentos
frequentes do setpoint, para atividade de setpoint, e não para uma sintonia ruim.

## Limites

- PV e SP precisam estar na mesma unidade de engenharia.
- Um erro alto pode vir de restrições, perturbações ou de um setpoint que o processo não consegue
  alcançar, não só da sintonia.
- Sem uma amplitude, o tamanho do setpoint é a escala: correto para PVs longe de zero (vazões,
  níveis, temperaturas em °C), apertado demais para uma mantida perto de zero (uma pressão
  manométrica, um diferencial). Dê a essas malhas o `pv_span` ou um `error_tolerance` absoluto. O
  PlantCraft ainda não guarda as faixas dos sinais; quando guardar, a amplitude poderá vir de lá
  (lacuna G36).
- O erro não é comparado aqui com o que o melhor controlador possível alcançaria: isso é o índice
  de variância mínima (Harris), `harris_index`.
