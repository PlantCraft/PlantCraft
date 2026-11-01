# Algoritmos

Um algoritmo é um diagrama de blocos: os sinais entram pela esquerda, passam por verificações de
qualidade de dados, transformações e métodos, são combinados e saem como saídas à direita. Cada
ligação une duas portas do mesmo tipo, e o algoritmo é verificado antes de rodar ou ser salvo: um
bloco com uma entrada não ligada, uma ligação entre portas que não combinam ou um laço nas ligações
é marcado no bloco, em palavras.

O PlantCraft fornece seis algoritmos, somente leitura, com **PlantCraft** como autor:

- **Malha de vazão**: o padrão das malhas de vazão e das malhas de tipo desconhecido. Erro PV–SP,
  saturação da saída e qualidade de amostragem compõem a saúde (0 a 100); curso da válvula e
  agarramento (stiction) são julgados com eles; oscilação e ruído são sinalizados ao lado dela;
  modo manual, movimentos do setpoint e intervenções são contexto.
- **Malha de nível**: o padrão das malhas de nível, para níveis mantidos apertados no setpoint:
  erro, saída e curso da válvula compõem a saúde; oscilação e agarramento são sinalizados ao lado
  dela.
- **Nível pulmão**: para níveis que devem absorver perturbações dentro de uma faixa.
- **Malha de temperatura ou pressão**: o padrão das malhas de temperatura, pressão e composição:
  malhas lentas julgadas pelo índice de Harris (variância contra o controle de variância mínima)
  ao lado do erro e da saída.
- **Qualidade dos sinais**: as verificações de qualidade de dados em todos os sinais, no seu
  próprio monitor.
- **Gêmeo da unidade**: um modelo de processo roda ao lado de uma unidade sobre os sinais dela, e a
  diferença entre o que ele prevê e o que a planta mede é julgada contra a operação normal. Roda em
  ativos.

Na planta de demonstração do Simulator, o Analytics adiciona sozinho seus gêmeos (os fornos e os
modelos de processo de duas malhas) na primeira vez que encontra a planta: calibrados nas últimas
horas e agendados nos seus ativos, para que os modelos rodem desde o início. Um gêmeo excluído
continua excluído (**Adicionar os exemplos de modelo da planta** o traz de volta). As verificações
de válvula e de oscilação são blocos da biblioteca *Desempenho de malhas de controle*: arraste-os
para qualquer algoritmo.

Todo algoritmo tem **rótulos** (control loop, data quality, digital twin, ou os seus), um
**responsável**, uma **versão** (cada salvamento acrescenta uma) e, quando definido, um **grupo
responsável**: os membros e coordenadores do grupo o editam, os demais o leem. A lista diz quantos
ativos usam cada um.

Para alterar um, **Duplique-o** e edite a cópia; uma malha ou um monitor passa então a usar a
cópia.

## Desenhando um algoritmo

Abra um algoritmo e o editor abre na sua própria janela. Arraste blocos da paleta à esquerda
(busque pelo nome), ligue uma saída a uma entrada (as entradas compatíveis se acendem) e defina os
parâmetros de um bloco no painel à direita, onde cada porta e parâmetro é descrito.

- **As cores das ligações** dizem o que passa: azul um sinal ao longo do tempo, violeta o modo,
  âmbar um número, verde um resultado (ok, atenção, ruim ou desconhecido, com uma pontuação de 0 a
  100 e uma frase), cinza uma condição (partes da janela).
- **A verificação dos dados da malha** fica depois dos sinais: repassa PV, SP, OP e modo quando os
  dados são utilizáveis, e nada (com o motivo) quando não são, para que os métodos depois dela não
  julguem dados ruins.
- **Transformações** preparam os sinais: aritmética (*Expressão*, como `a * b / c`, *Unidade de
  engenharia*), filtros (*Média móvel*, *Filtro passa-baixas (primeira ordem)*, *Derivada (taxa de variação)*, *Reamostrar (por período)*, *Remover
  tendência*, *Atraso*), *Selecionar por condição* e *Só em operação*, que mantém a operação
  estável e deixa de fora partidas e paradas.
- **Estatística** resume um sinal ao longo da janela, ou só onde uma condição vale: *Média*,
  *Desvio padrão*, *Percentil*, *Histograma*, *Correlação* (com a melhor defasagem), *Mudanças em
  degrau* e *Tempo fora dos limites*.
- **Equipamentos**: *UA do trocador de calor* (acompanha a incrustação contra o UA limpo) e
  *Eficiência da bomba* (contra a curva do fabricante).
- **Condições** (ligações cinza) marcam partes da janela: *Comparar com um limite* (uma vazão de
  carga acima do mínimo: a unidade roda) e *E / OU / NÃO* para combiná-las.
- **Lógica**: *Pior de* mantém o pior resultado; *Média das entradas* pontua a média contra dois limites;
  *Regra (se … então)* substitui um resultado quando um teste está ruim ("se os dados da PV estão ruins, o
  resultado da válvula não é confiável"); *Verificação de limite* transforma um número em um resultado.
- **Saídas**: *Saúde da malha* (a saúde e os achados da malha), *Resultado no ativo* (um resultado
  com nome que todo app lê), *Mensagem* (um evento quando sua entrada fica ruim, encerrado quando
  se recupera). Qualquer número, resultado ou série também pode ser **gravado no Historian** com a
  chave na sua porta: Tendências, Dashboards e o assistente passam então a lê-lo. Em ativos, cada
  monitor diz nas suas **Saídas gravadas** quais delas guarda e por quanto tempo (um resultado
  para sempre, outros valores 400 dias, uma série as últimas 10 execuções, por padrão), com quanto
  isso custa; o Historian mostra as execuções de uma série uma sobre a outra.

**Testar** roda o diagrama nos dados recentes de uma malha sem salvar nada e mostra em cada ligação
o que ela transportou. Depois de salvar, **Monitor** o roda a cada N minutos em todas as malhas ou
nas escolhidas; cada execução aparece em **Resultados > Histórico de execuções**. O painel ao lado
do diagrama diz **onde é usado**: as malhas que usam o algoritmo e seus monitores.

Cada algoritmo tem sua documentação nas mesmas cinco partes (para que serve, os ativos que lê,
quando usar, como ler o resultado, instruções para o assistente). O que fica vazio é escrito a
partir do diagrama, e o assistente o lê quando alguém pergunta sobre o algoritmo.

## Algoritmos em ativos e modelos de processo

Um algoritmo também pode trabalhar sobre **ativos**: uma unidade, um forno, qualquer ativo do
PlantCraft. Escolha *Ativos* em *Trabalha em*, depois indique os ativos e defina com que
frequência roda (a partir de a cada 10 segundos), até quando no passado cada execução lê e o passo
em que lê. Seus blocos de Sinal leem um papel do ativo, um papel de outro ativo (uma malha da
unidade) ou um sinal pelo id. **Testar** o roda na janela de um ativo, terminando agora ou em um
momento escolhido; a página do algoritmo mostra sua última execução em cada ativo, e a página de
um ativo lista os algoritmos que rodam nele.

A biblioteca **Modelos** contém um bloco por modelo de processo publicado (uma FMU): suas entradas
são as entradas do modelo, mais o valor medido de cada saída, e ele dá o que o modelo prevê e o
resíduo (medido menos previsto). Ligue os resíduos a um bloco **Desvio (T²)**, que os julga contra
a operação normal.

A biblioteca **Estimadores** contém estimadores que não precisam de um modelo próprio: um
filtro de Kalman de uma PV a partir da sua válvula, e uma estimativa de deriva do sensor. O
algoritmo **Sensor virtual** liga os dois em uma malha, grava-os como séries e julga a deriva com
uma verificação de limite.

Um modelo vem do PlantCraft Models: na execução de uma FMU exportada, um administrador clica em
**Publicar no Analytics**, e o modelo passa a ser na hora um bloco da biblioteca. **Montar um
algoritmo com ele** ali (ou **Novo algoritmo com este modelo** na página do bloco) abre o editor
em um novo algoritmo sobre ativos em torno do modelo: um bloco de Sinal em cada entrada e saída, o
modelo, o Desvio, um resultado e uma mensagem. Escolha o papel por trás de cada bloco de Sinal,
calibre, escolha os ativos e salve.

**Calibrar** ensina ao bloco Desvio como é o normal. Selecione o bloco, escolha um ativo e um
período em que a unidade operou normalmente, e clique em *Calibrar*: o algoritmo roda sobre o
período como teria rodado, execução após execução, e a média e a dispersão dos resíduos viram a
calibração do bloco. Ele diz quantas execuções usou, quais deixou de fora e por quê, e avisa quando
um resíduo fica longe de zero (o modelo ou um desvio de sensor). Salve o algoritmo para mantê-la;
até ser calibrado, um bloco não julga nada e diz isso.
