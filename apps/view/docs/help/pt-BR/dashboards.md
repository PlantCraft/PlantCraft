# Dashboards

Um dashboard é uma tela de painéis sobre os sinais e ativos da planta, lidos do PlantCraft.
Os dashboards ficam em pastas; uma pasta diz quem vê e quem edita os seus dashboards.

- **Novo dashboard** pede um nome, uma pasta e o ponto de partida: uma grade vazia, um modelo
  construído a partir dos ativos da planta (um detalhe de malha, uma visão geral de unidade) ou um
  arquivo exportado do View. O editor abre com ele; nada é salvo até você clicar em **Salvar**
  (Cancelar não deixa rastro).
- **Editar** abre o dashboard para alterações: adicione, altere, arraste, redimensione e remova
  painéis, depois **Salvar**. Se outra pessoa o salvou nesse meio-tempo, o Dashboards pergunta antes
  de substituir a versão dela.
- **Atualizar** lê os painéis de novo a cada 15 s a 5 min, ou só quando você pede.
- **Tela cheia** oculta tudo menos os painéis, para uma parede de sala de controle.
- **Tempo** define uma janela para todos os painéis (ou cada painel mantém a sua). O endereço no
  navegador guarda a página, as variáveis (`?var-loop=fic-101`), a janela e a tela cheia, assim um
  favorito abre a mesma visão.

## Variáveis

As variáveis são os seletores no topo de um dashboard (Configuração › Variáveis), como no Grafana.
Um dashboard então atende todos os ativos de um tipo:

| Tipo | Oferece |
|---|---|
| Ativo | Os ativos de um tipo (todas as malhas, todas as bombas); sob uma variável **mãe**, só os ativos sob os escolhidos nela |
| Personalizada | Uma lista que você escreve (`PV, SP, OP` ou `north, south`) |
| Intervalo | Janelas de tempo (`1h, 8h, 24h`), para painéis que usam `${period}` como janela |

Uma variável pode receber **vários valores** e oferecer **Todos**. Os painéis a usam como `${name}`
em uma linha de sinal (modo Variável, ou dentro de um nome de sinal: `FIC-${unit}.PV`), em um
título, em uma nota ou em uma janela. Um painel com **Repetir** é desenhado uma vez por valor
escolhido, lado a lado ou um embaixo do outro; durante a edição aparece uma vez. Um seletor sem
opções avisa, em vez de mostrar painéis vazios. Os dashboards feitos com o antigo seletor de
**Ativo** abrem com ele como primeira variável.

## Páginas

Um dashboard pode ter até 10 páginas, mostradas como abas no topo (um dashboard com uma página não
mostra abas). Durante a edição, **Adicionar página** adiciona uma; o nome da página, as setas e a
lixeira ao lado dela renomeiam, movem e removem a página mostrada (remover uma página remove os
painéis dela). A **Página** de um painel, no editor de painel, o move para outra página. O ativo, a
janela de tempo e a atualização são do dashboard: ficam quando você muda de página. Só a página
mostrada lê dados.

**Virar as páginas em tela cheia** (Configuração › Tempo, com duas páginas ou mais) mostra a próxima
página a cada 30 s, 1 min ou 5 min em tela cheia e nos links públicos: uma tela de sala de controle
passa por todas as páginas.

## Pastas

A lista mostra os dashboards por pasta; **General** guarda os que estão fora de qualquer pasta, e
todos com acesso ao View os veem. **Nova pasta** (editores) dá nome a uma pasta e diz quem pode
usá-la:

- **Quem vê os dashboards dela**: todos com acesso ao View, ou só algumas pessoas e grupos da
  plataforma (Configurações › Pessoas › Grupos no PlantCraft). Os demais não veem a pasta nem os
  dashboards dela em lugar nenhum: nem na lista, nem nas páginas de ativo, nem nos widgets da Visão
  geral, nem na API.
- **Quem edita os dashboards dela**: todos os editores do View, ou só algumas pessoas e grupos. Só
  os editores do View entre eles alteram, compartilham, adicionam ou excluem os dashboards dela;
  eles sempre veem a pasta.

Os administradores veem e alteram todas as pastas. Uma pasta é excluída quando está vazia. Um link
público continua mostrando o seu dashboard a quem o tem, qualquer que seja a pasta.

## Compartilhar, Configuração, Editar

Ao lado do seletor de tempo: **Compartilhar** (links públicos), **Configuração** e **Editar**. A
Configuração salva na hora, sem entrar no editor; dentro do editor, ela altera o que **Salvar**
salva.

| Seção | O que contém |
|---|---|
| General | Nome, pasta, descrição, rótulos (a busca da lista os encontra) |
| Tempo | A janela com que abre, a atualização, a virada de página em tela cheia |
| Exibição | **Cursor compartilhado**: passar o mouse sobre uma tendência marca o mesmo instante nas outras. **Quiosque**: a tela cheia e os links públicos mostram só os painéis (Esc sai) |
| Variáveis | Os seletores no topo: variáveis de ativo, personalizadas e de intervalo, os seus padrões, vários valores, Todos, uma mãe |
| Versões | Os últimos 30 salvamentos, quem e quando; **Restaurar** salva de novo um antigo como o mais novo |
| JSON | O dashboard como arquivo, para começar um dashboard a partir dele em outro lugar |

Um dashboard salvo lê os dados da planta com a chave de app do View, assim todos os espectadores
veem os mesmos números, e uma leitura é compartilhada por todos os espectadores por alguns
segundos.
