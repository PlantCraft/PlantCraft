# Painéis

| Tipo | Mostra | Sinais |
|---|---|---|
| Valor | Um valor (último, média, mín., máx., ...) por sinal ao longo de uma janela, colorido pelos seus limiares, com a sua linha embaixo se você quiser | até 24 |
| Indicador | Um valor em um mostrador (ou um indicador de barra), com as faixas de limiar; um mostrador por sinal. Estilo **Indicador analógico (ISA-101)**: uma barra cinza com a faixa normal, os limites LL, L, H e HH dos limiares e o setpoint (um sinal de papel SP do mesmo ativo); o ponteiro só ganha cor fora do normal | até 24 |
| Tendência | Linhas ao longo de uma janela; duas unidades ganham dois eixos; limiares como linhas ou áreas | até 24 |
| Gráfico de barras | Um valor por sinal, vertical ou horizontal, colorido pelos limiares | até 24 |
| Tabela | Último, média, mín. e máx. por sinal, células coloridas pelos limiares | até 24 |
| Dispersão (X-Y) | Um sinal contra outro, na mesma grade de tempo: o primeiro é x, o segundo y (PV contra OP mostra uma válvula com agarramento) | 2 |
| Texto | Uma nota: para que serve o dashboard, o que observar, quem chamar | nenhum |
| Controlador multivariável | Um APC de terceiros, somente leitura: cada variável manipulada (MV) e controlada (CV) com o seu valor, limites baixo e alto, alvo em regime permanente, status e preço sombra agora, uma barra da sua faixa (o valor como ponteiro, o alvo como marca vazada) e o seu valor e alvo ao longo do intervalo de tempo (o horizonte). Uma variável cujo alvo (senão o valor) está dentro da sua banda de um limite é marcada **No limite alto** ou **No limite baixo** | nenhum: o controlador |

O controlador é um ativo do tipo `apc` (papéis `on`, `mode`; atributos `vendor`, `cost_unit`) com
ativos do tipo `apc_mv` e `apc_cv` sob ele (papéis `value`, `lo`, `hi`, `target`, `status`,
`shadow_price`; atributo `limit_band`, 1 % de alto menos baixo quando vazio). O Analytics lê os
mesmos nomes. O View nunca escreve no controlador.

Os painéis salvos antes da rodada 7 abrem como antes: um KPI ou um painel de "valor e linha" agora é
um Valor (o segundo com a linha ligada), e os seus limites agora são limiares.

## O editor de painel

**Adicionar painel** abre o editor em tela cheia. Primeiro escolha o **tipo de painel**; a prévia
ocupa a esquerda e as opções ficam em grupos à direita, com uma caixa de busca que mantém só as
opções cujo nome corresponde. **Visualização**, no topo, muda o tipo depois: os sinais, os
limiares, os mapeamentos e as substituições ficam. **Aplicar** coloca o painel no dashboard (o
dashboard é salvo com **Salvar**), **Descartar** o deixa como estava.

**Sinais.** Cada linha de um painel é uma destas:

- **Sinal**: um sinal do PlantCraft, por nome ou descrição.
- **Ativo**: um ativo e um papel de sinal, ou **todos os sinais do ativo**; os botões de papel
  abaixo dele mantêm só alguns papéis (PV, SP, OP, ...).
- **Variável**: o ativo escolhido em uma variável do dashboard (`${loop}`), com um papel ou todos os
  papéis. O painel segue o seletor; veja [Dashboards](dashboards.md#variáveis).

Um painel tem até 12 linhas, que representam no máximo 24 sinais (uma nota avisa quando mais foram
cortados). Um painel novo de tendência, barras ou tabela começa com todos os sinais do ativo; um de
valor ou indicador, com um.

## Opções

| Grupo | O que define |
|---|---|
| Painel | Título, descrição, página, janela de tempo própria |
| Valor, Indicador, Gráfico de barras, Tabela, Gráfico, Dispersão | O que o tipo desenha: o valor (último, média, ...), a linha sob um valor, o mostrador ou o indicador de barra, a direção das barras, o estilo da linha e os pontos, as colunas da tabela |
| Legenda, Eixo | Posição e tabela da legenda (com último, média, mín., máx.), rótulos dos eixos, escala, mín. e máx. flexíveis |
| Opções padrão | Unidade, casas decimais, mín. e máx., a faixa normal (a linha de um valor e o indicador analógico a sombreiam; vazio: entre o degrau normal dos limiares e o seguinte), cor dos valores |
| Limiares | Degraus a partir de uma cor base: cada degrau tem um valor e uma cor; **absoluto** ou **percentual** do mín. ao máx.; em tendências e barras, mostrados como linhas, áreas, os dois ou nada, com os seus rótulos |
| Mapeamentos de valor | Um valor ou uma faixa mostrado como uma palavra e uma cor (0 como "Parada", 1 como "Funcionando") |
| Substituições | Outras opções só para algumas linhas, escolhidas por papel, sinal ou nome (o SP tracejado, a OP no eixo direito) |
| Layout | Largura e altura em células da grade |
| Opções de repetição | Repetir o painel para cada valor de uma variável, lado a lado ou um embaixo do outro |

As cores continuam legíveis nos temas claro e escuro: uma cor próxima demais do fundo é escurecida
ou clareada até ficar legível, e o texto em uma célula preenchida é branco ou preto, o que for mais
legível.

## Tamanho e posição

A grade tem 12 colunas; uma linha tem cerca de 90 pixels. Em **Editar**, arraste um painel pela
barra de título e redimensione-o pelo canto inferior direito; os outros painéis saem do caminho.
**Duplicar** coloca uma cópia embaixo dele. Os painéis com gráfico, mostrador ou tabela ocupam pelo
menos 2 linhas. Em telas mais estreitas, os painéis ocupam metade da largura ou ela toda, e em um
celular cada painel ocupa a largura toda na sua própria altura.

**Tela cheia.** Os painéis de tendência, barras e dispersão têm um botão de tela cheia no canto: o
painel ocupa a janela, com ampliação, deslocamento, redefinição e download da imagem. Esc fecha. A
página Tendências tem o seu próprio botão **Tela cheia** acima do gráfico.

**Resultados de outros apps.** Os painéis de valor, barras e tabela também podem mostrar o que
outro app instalado publicou sobre um ativo ou sinal, como a saúde da malha ou a qualidade de sinal
do Analytics: escolha o ativo, depois o resultado em "Mostra". A cor é o status do próprio app (OK,
Atenção, Crítico), não os limiares do painel; o valor é a sua nota de 0 a 100. Um resultado que o
app não atualizou a tempo aparece como desatualizado e desconhecido. Em um painel de tendência, a
mesma escolha desenha o histórico do resultado, quando o app o arquiva (o Analytics guarda a saúde
de cada malha ao longo do tempo).

**As janelas** vão de segundos a 366 dias. Uma tendência desenha no máximo cerca de 600 pontos por
linha, cada um a média do seu passo. Quando uma janela não tem amostras, a tendência mostra os
dados mais recentes que encontra e avisa abaixo do gráfico.
