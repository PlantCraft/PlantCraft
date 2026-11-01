# Visão geral

A primeira página do Analytics: um quadro de widgets que só mostra, sem botões por cima. Uma
execução começa em Monitores (o **Executar agora** de cada monitor), nunca aqui.

O quadro de uma pessoa nova responde a uma pergunta: quais ativos e sinais estão ruins agora, e
onde:

- **Resultados por estado**: todos os resultados divididos em alarme, atenção, desconhecido e OK.
  Cada parte abre os resultados correspondentes.
- **Em alarme, 14 dias**: quantos estavam em alarme e em atenção no fim de cada dia.
- **Mapa de saúde**: um quadrado por ativo e sinal, colorido pelo estado e agrupado por área.
  Cada quadrado abre seu resultado.
- **Piores resultados**: os que estão em alarme ou atenção, com a menor saúde, qualidade ou
  pontuação primeiro.
- **Monitores**: cada monitor, quando roda e como terminou sua última execução.
- **Fila**: o que aguarda e o que roda agora, e a fila nas últimas 24 horas.
- **Horas-malha perdidas, 7 dias**: por área, o tempo em que cada malha não estava controlando,
  dividido por causa: fora do modo normal, saída em um limite, oscilando e sinal ruim.
- **Controle efetivo**: as malhas com a menor pontuação primeiro. A pontuação é a fração do tempo
  em modo normal, vezes dentro da faixa de operação, vezes com a saída fora dos limites.
- **Oscilações compartilhadas por várias malhas**: malhas que ciclam com períodos a menos de 15%
  umas das outras, agrupadas. A malha a olhar primeiro em cada grupo é a que tem agarramento
  (stiction); depois, a de ciclo mais regular.
- **Mapa da planta**: todas as malhas coloridas pelo KPI escolhido (saúde, controle efetivo, tempo
  em modo normal, tempo dentro da faixa, tempo com a saída fora dos limites). Bom é a partir de
  90, regular a partir de 75, fraco a partir de 50, ruim abaixo disso. **Mapa de calor** agrupa as
  malhas por área; o treemap as dimensiona pela criticidade, então as malhas críticas ocupam mais
  espaço. Cada malha abre sua página.

Mais widgets aguardam em **Personalizar**: **Analytics: mais perto do limite** lista as malhas
cuja saúde está caindo e quantos dias faltam até ela chegar ao limite de alarme (50). A previsão é
uma reta ajustada aos últimos 14 dias, mostrada só quando se ajusta bem (R² de pelo menos 0,5) e o
limite está a menos de um ano. **Analytics: controladores multivariáveis** mostra cada APC de
terceiros com seu limite ativo mais caro.

**Personalizar** adiciona, move e remove widgets só para você: um monitor, um resultado, a última
execução e os outros que o Analytics publica. Os mesmos widgets podem ir para o Hoje do Desk.
