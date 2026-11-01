# De onde vêm as malhas e suas configurações

As malhas vêm do catálogo de ativos do PlantCraft: todo ativo do tipo malha de controle, com seus
sinais por papel (PV, SP, OP, modo, secundário) e seu cadastro (tipo de malha, criticidade, ação,
controlador, relações). O cadastro é editado no PlantCraft.

O tipo de malha e a criticidade dão a cada malha seu algoritmo inicial, seus parâmetros e seu peso
na classificação (veja Padrões de análise por tipo de malha). Um ajuste alterado na página da malha
passa a ser do Analytics a partir de então: a página o marca como "definido aqui", e "Usar o
cadastro do ativo" o devolve.

Um ativo de malha sem sinal para um papel que seu tipo exige (PV e OP) é listado como Cadastro
incompleto e não é analisado até que os sinais sejam vinculados na página do ativo no PlantCraft.

A criticidade do cadastro (baixa, média, alta) pondera a classificação: os pontos perdidos a partir
de 100 vezes 0,6, 1,0 ou 1,5; crítica (2,0) é definida só aqui.

## Na página da malha

- **Onde a saída passou a janela**: a fração da janela em cada faixa de 5% da saída. Uma malha que
  vive perto de 0 ou 100% está saturada; uma espremida em poucos por cento tem pouca folga.
- **Degraus de setpoint** (somente leitura): "Encontrar degraus" lista cada mudança de setpoint da
  última janela que se destaca do ruído da PV e foi mantida por pelo menos dez amostras, com a
  resposta da PV: sobressinal além do novo setpoint, tempo de subida (10 a 90% do degrau), tempo de
  acomodação (até a PV ficar dentro de 5% do degrau, mais largo quando a PV é ruidosa) e IAE
  dividido pelo tamanho do degrau, em segundos, para que degraus de tamanhos diferentes se
  comparem. Uma rampa curta de até três amostras conta como um degrau; degraus dados em manual
  ficam de fora. As medianas ficam acima da tabela.
- **Sugerir sintonia** (somente leitura): ajusta um modelo de primeira ordem com tempo morto da OP
  para a PV na última janela e dá ajustes PI pelas regras Lambda (IMC) para três velocidades:
  apertada (lambda = tempo morto), moderada (lambda = constante de tempo) e robusta (lambda = 3
  constantes de tempo), com a ação do controlador. Dados tomados em malha fechada são um
  experimento fraco, então tome-os como ponto de partida para um teste de degrau. A página diz por
  que uma sugestão não é confiável: o ajuste explica menos da metade da PV, a OP quase não se moveu,
  ou a constante de tempo é menor que uma amostra. Nada é enviado ao controlador.
- **Registrar como referência** (editores): guarda a última execução da malha como aquela com que
  comparar, depois do comissionamento ou de uma nova sintonia. A página então mostra a saúde na
  época e agora e, para cada método, seu estado, a variação da pontuação e o indicador que mais se
  moveu. Uma referência por malha: registrar de novo a substitui.
