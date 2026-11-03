# Tendências

**Tendências** desenha sinais ao longo de um período em um gráfico ou em subgráficos empilhados que
compartilham o eixo de tempo. Salve uma tendência para abri-la de novo, ou baixe o que ela mostra em
CSV.

- **Período**: dos últimos 15 minutos a 30 dias, ou um "de – até" fixo.
- **Intervalo**: quanto tempo cada valor desenhado cobre. "Automático" o escolhe a partir do período
  (cerca de 600 valores por linha); "Como gravado" desenha toda amostra.
- Adicione sinais a um gráfico com a busca abaixo dele; até 8 linhas por gráfico e 6 gráficos.
- **Comparar com**: desenha até três períodos anteriores sobre o da própria tendência, cada linha
  pontilhada e mais clara na cor da sua linha e nomeada pelo seu período: o **período anterior**
  (logo antes, tão longo quanto o da tendência), **1 dia antes** (ontem sobre hoje), **1 semana
  antes** ou **4 semanas antes**. Cada período anterior é lido no intervalo da tendência e
  deslocado para o seu eixo de tempo, assim o hover mostra o relógio de hoje; o nome da linha diz
  qual período ela é. Os estados (sinais de texto) não são comparados. Salvo com a tendência.

## Cada linha

Clique no nome de uma linha para configurá-la sozinha, à parte das outras linhas:

- **Intervalo**: o da tendência (o padrão) ou o da própria linha, de 1 minuto a 1 dia ou como
  gravado. PV a cada minuto ao lado de SP a cada hora no mesmo gráfico são duas linhas com dois
  intervalos.
- **Cada intervalo mostra**: a média (o padrão), o último valor, o primeiro valor, o mínimo ou o
  máximo de cada intervalo. O mesmo sinal pode ser desenhado duas vezes, por exemplo a sua média e
  o seu máximo. Os resumos diferentes da média leem as amostras como gravadas; em um período muito
  longo com amostras demais, a linha volta para a média e avisa abaixo do gráfico.
- **Desenhar como**: uma linha, pontos ou os dois; entre amostras em reta, em degraus (cada valor
  mantido até o próximo, como um controlador o vê) ou suave.
- **Cor** (automática ou escolhida), **traço**, **espessura da linha** e **tamanho do ponto**.
- **Eixo Y**: esquerdo, ou direito com escala própria, para comparar sinais de faixas diferentes no
  mesmo gráfico.

O CSV tem uma coluna por linha desenhada, nomeada com o seu resumo quando não é a média.

## O gráfico

- Um eixo indica a sua unidade só quando todas as linhas nele têm a mesma; com duas unidades, a
  legenda e o hover ainda dão a cada linha a sua.
- **Tela cheia**, acima do gráfico à esquerda, mostra só o gráfico; Esc sai.
- **Gráfico**: "Como a plataforma" segue o seu tema; **Claro** ou **Escuro** fixa as cores do
  gráfico, a imagem incluída, qualquer que seja o tema da plataforma. A escolha fica neste
  navegador.
- Os botões do Plotly, no canto superior direito do gráfico, ampliam, deslocam e baixam o gráfico
  como um PNG nomeado pela tendência.
