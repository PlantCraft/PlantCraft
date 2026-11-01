# Processo

Uma **tela de processo** desenha a planta como os operadores a conhecem: os equipamentos da
biblioteca de símbolos ligados pelas suas linhas, com os valores da planta sobre eles. As cores
dizem o estado num relance, os tanques se enchem com o seu nível, as bombas acendem quando
funcionam e as linhas se movem enquanto algo flui. As telas de processo só leem: nada em uma tela
escreve na planta.

## Páginas

Uma tela de processo contém a planta: cada unidade ou área na sua própria página, com as abas sob o
nome. No editor, **Adicionar página** cria uma; o nome da página, a sua posição e **Remover página**
ficam ao lado das abas. Um símbolo, valor ou texto pode abrir outra página (Um clique abre › Outra
página), como um conector de fora de página.

Uma tela desenhada para a planta inteira abre na sua **Visão geral da planta** (Nível 1): um bloco
por unidade com a contagem de equipamentos e de malhas e as bolhas de saúde das malhas; um clique
abre a página da unidade, e **‹ Visão geral da planta** em cada página de unidade leva de volta.

## Acompanhar uma tela

- **Ao vivo** mostra os valores agora, atualizados a cada poucos segundos (a cadência da própria
  tela).
- **Cores**: verde é normal, âmbar uma atenção, vermelho um alarme (pisca), cinza sem dados. Cinza
  também significa que um valor não mudou por 15 minutos: um número velho nunca aparece como uma
  planta saudável.
- Um símbolo vinculado a um estado de alarme do Alarms ganha uma marca no canto enquanto um alarme
  está ativo, pela sua prioridade mais urgente (ISA-101): um quadrado com 1 para crítica, um
  triângulo com 2 para alta, um losango com 3 para média e um círculo com 4 para baixa. A forma e o
  número se leem sem cor.
- Aponte para um elemento para ler os seus valores, a unidade deles e por que um não pode ser lido.
  A lista sob a tela indica todos os valores que não podem ser lidos.
- Um desenho grande pode nomear as suas **partes** (Editar › Tela de processo › Partes): abas sobre
  ele, **Visão geral** para o desenho inteiro e uma por parte, ampliada; a aba da parte à vista fica
  marcada, e o endereço a guarda (`?part=`).
- Um clique em um valor desenha a sua tendência em uma janela sobre a tela, com o período, o
  intervalo e a aparência de cada linha como em Tendências; **Abrir em Tendências** continua com ela
  lá.
- Um clique em um equipamento abre o painel dele ao lado da tela: os seus valores no desenho, os
  seus sinais (cada um a uma tendência de distância), os dashboards que o mostram e **Página do
  ativo**. Um elemento que o editor ligou a outro lugar abre esse lugar: outra tela de processo ou um
  dashboard. Uma tela aberta assim mostra **Voltar** com o nome da primeira, que retorna à página
  que você deixou.
- **Tela cheia** é a do próprio navegador: só a tela de processo, ao vivo, para uma tela de sala de
  controle, com a tendência e o painel do ativo abrindo dentro dela; Esc sai.
- O nível de um vaso enche a própria forma do vaso, com a superfície do líquido desenhada como uma
  linha.

## Compartilhar uma tela

Os editores da pasta de uma tela de processo a compartilham com **Compartilhar**, como um
dashboard: um **link público** abre só esta tela, somente leitura e sem entrar, para uma tela de
parede ou um colega sem conta.

- Copie o link quando ele for criado: ele é mostrado só uma vez. Ele abre por 7 a 365 dias (um
  administrador pode criar um que abre até ser revogado), e para na hora quando você o revoga ou
  exclui a tela.
- O link mostra a tela ao vivo, com a sua barra de tempo para reproduzir a janela. Adicione
  `?screen=1` ao link para um quiosque: só a tela de processo, ao vivo, ocupando a tela.
- Os cliques em uma tela compartilhada não abrem nada: os seus links levam a páginas que exigem
  entrar.
- Os administradores revisam todos os links da instalação (dashboards, relatórios e telas de
  processo) em **Dashboards › Links públicos**.

## Uma tela de processo em um dashboard

Um dashboard pode mostrar uma tela de processo salva em um painel: **Editar › Adicionar painel ›
Tela de processo**, depois escolha a tela. O painel a desenha ao vivo, ajustada ao tamanho,
atualizada com o dashboard; ele lê a janela de **Tempo** do dashboard (senão, a do próprio painel) e
um clique abre a página da tela.

Quem vê a tela segue a pasta dela: um espectador que não pode ver essa pasta, ou um link público do
dashboard quando a tela está em uma pasta reservada a algumas pessoas, vê "indisponível" no lugar,
e o mesmo vale para todos depois que a tela é excluída. Os relatórios não aceitam painel de tela de
processo.

Para passar por várias telas de processo em uma tela de sala de controle, coloque cada uma em uma
página de um dashboard, defina na **Configuração** do dashboard que ele mostre a próxima página de
tempos em tempos, e abra-o em tela cheia ou pelo seu link público.

## Voltar no tempo

A barra de tempo lê a janela inteira de uma vez, assim percorrê-la não pede nada novo à plataforma.

- Escolha a **janela** (15 minutos a 7 dias) e arraste o cursor: a tela mostra os valores daquele
  instante.
- **Reproduzir** roda a janela de 1x a 600x; **Fim do período** move a janela para qualquer momento
  passado.
- Os estados que outros apps publicam (alarmes, saúde da malha) aparecem só ao vivo; na reprodução
  ficam cinza.

## Desenhar uma tela

Os editores desenham as telas de processo: **Nova tela de processo**, ou **Editar** em uma tela.

1. **Arraste equipamentos** da biblioteca à esquerda para a tela de desenho (ou clique neles para
   soltá-los no meio). A busca encontra um símbolo pelo nome ou pelo que ele é: bomba, tanque,
   válvula, coluna.
2. **Ligue-o**: arraste de uma porta (os pequenos círculos de um símbolo) até outro símbolo ou uma
   das portas dele. A linha se roteia sozinha com curvas em ângulo reto e acompanha os símbolos
   quando eles se movem.
3. **Vincule-o**: clique em um símbolo e escolha o **ativo que ele desenha** (P-101, TK-1). A cor, o
   nível e o funcionamento são vinculados na hora a partir dos papéis de sinal do ativo; altere
   qualquer um deles no painel. **Valor** adiciona um número ao lado do símbolo selecionado (a PV
   primeiro), com os seus próprios limites. Marque **Indicador analógico (ISA-101)** para desenhar
   uma barra cinza abaixo dele: a faixa normal como uma banda mais escura (da atenção baixa à atenção
   alta quando não definida), os limites como marcas LL, L, H e HH, o setpoint (o SP do ativo
   primeiro) como uma marca vazada e o valor como um ponteiro. Só o ponteiro ganha cor, e só fora do
   normal.
4. **Salvar**. Nada é salvo antes; Cancelar deixa a tela como estava.

Ou comece de um rascunho: **A partir dos ativos** dispõe uma unidade a partir dos seus
equipamentos, malhas e relações (cada um com os seus vínculos), ou **a planta inteira**: uma visão
geral e uma página por unidade, e **Rascunho com o assistente** faz um rascunho a partir do que você
descreve (quando o uso de modelo de linguagem *diagram-draft* está ligado em Setup). Os dois
substituem a tela de desenho, Desfazer a traz de volta, e uma nota diz o que ficou de fora. Mova as
coisas para onde quiser, depois salve.

Um símbolo selecionado tem uma alça em cada canto: arraste uma para redimensioná-lo (Shift libera as
proporções). Uma linha selecionada tem uma alça em cada trecho que pode se mover: arraste-a para
mover esse trecho, e as curvas continuam em ângulo reto; **Esquadrar a rota de novo**, no painel
dela, desfaz as curvas. **Versões** (o relógio na barra de ferramentas) lista os últimos 30
salvamentos e traz um de volta para a tela de desenho; salve para mantê-lo.

Teclas: Ctrl+Z e Ctrl+Y desfazem e refazem, Delete remove, Ctrl+C, Ctrl+V e Ctrl+D copiam, as setas
deslocam (Shift para passos maiores), R gira, F espelha, Esc limpa a seleção. Ctrl e a roda do mouse
ampliam; Alt e arrastar, ou o botão do meio, deslocam a vista.

O **tipo** de uma linha a desenha como tubulação de processo (a cor dela diz o que roda nela: água,
vapor, gás, óleo...), um sinal (tracejada) ou uma utilidade (pontilhada).
