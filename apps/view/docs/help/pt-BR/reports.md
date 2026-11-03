# Relatórios

Um **relatório** é um documento sobre um período, escrito como um notebook: células de texto em
Markdown, os mesmos painéis de um dashboard (KPIs, mostradores, tendências, barras, tabelas,
dispersão) e os eventos que os apps escreveram (alarmes, achados do Analytics). O View o transforma
em **PDF** em uma agenda e o envia a pessoas e grupos em **Mensagens › Notificações**, com o PDF a
um clique. Todo PDF gerado é guardado, assim o que foi enviado pode ser lido de novo como era. Ele
também é baixado como **Word**, como **página web** e como **Markdown**, e abre por um **link
público**.

Cada dashboard pode ter o seu relatório ao lado, na mesma pasta: **Novo relatório › Começar de um
dashboard** transforma as páginas dele em títulos e os painéis em células.

## O período

Todas as seções de um relatório leem o período do relatório, que termina quando o relatório é
gerado: um relatório gerado todo dia às 06:00 sobre **as últimas 24 horas** cobre das 06:00 do dia
anterior às 06:00 (o dia do turno). Os painéis não têm janela própria em um relatório.

Um relatório agendado pode, em vez disso, cobrir **períodos de calendário inteiros**: ontem de
meia-noite a meia-noite, a semana passada de segunda a domingo, as duas semanas antes de
segunda-feira, o mês passado ou o trimestre passado, no relógio da instalação. Todos os painéis
então leem o período que fechou, quando quer que o relatório seja gerado: um relatório mensal
enviado no dia 3 ainda cobre do primeiro ao último dia do mês anterior.

## Agenda e destinatários

**Configurações** define:

- **Repetir**: todo dia, toda semana ou a cada duas semanas (em um dia da semana), todo mês ou todo
  trimestre (no dia 1 a 28), em um horário do fuso horário da instalação. Os relatórios *Não
  agendados* são gerados só quando alguém pede.
- **Cobre**: o período, de 1 hora a um ano. Mudar a repetição sugere um período correspondente (um
  dia, 7, 14, 30 ou 90 dias). **Períodos de calendário inteiros** cobre, em vez disso, o último dia,
  semana, duas semanas, mês ou trimestre fechado.
- **Também quando um evento encerra um lote ou uma partida**: cada novo evento do tipo em **Gerado
  quando** (sobre o ativo em **Só sobre**, ou qualquer um) gera um relatório sobre o lote que ele
  encerra: a partir do evento mais recente do tipo em **De** sobre o mesmo ativo, senão a partir do
  início que o evento traz, senão o período acima antes dele; no máximo 31 dias. Cada lote é
  relatado uma vez.
- **Enviado para**: pessoas e grupos da plataforma. Elas recebem uma notificação por envio; só quem
  pode ver a pasta do relatório o abre. **Também por e-mail** adiciona um e-mail quando o PlantCraft
  envia e-mail e a pessoa permite.

Os próximos envios aparecem na Agenda do Desk, e o PlantCraft lista a agenda junto com as dos outros
apps.

## Montar um relatório

**Editar** abre o editor na própria página. Adicione células no fim, ou abaixo de qualquer célula
com o seu **+**:

- **Texto**: Markdown, escrito no lugar com a prévia ao lado (clique duas vezes em um texto para
  escrever nele; Shift+Enter conclui). `#` a `####` são títulos de quatro níveis, depois parágrafos,
  **negrito**, *itálico*, listas (`-`, `1.`), tabelas (`| a | b |`), citações (`>`) e links. Os
  títulos são as **seções** do relatório: a navegação ao lado da página, os marcadores do PDF, o
  painel de navegação do Word e o menu lateral da página web.
- **Painel**: um gráfico, KPIs ou uma tabela, montado no mesmo editor dos painéis de um dashboard.
  Um relatório indica os seus sinais e ativos (sem variáveis, sem painéis repetidos).
- **Eventos**: até 10 tipos de eventos dos apps instalados; a seção conta cada tipo no período e
  lista os mais recentes (até 100).
- **Quebra de página**: o PDF começa uma nova página ali.
- **Seção do assistente**: texto que o modelo de linguagem escreve a partir dos resultados mais
  recentes de malhas, qualidade de sinal e alarmes e dos eventos do período sobre os ativos que você
  escolhe (marque-os, ou descreva-os e o modelo os escolhe). **Requisitos (o prompt)** diz o que
  escrever e pode ser editado; o retorno sobre uma edição vai para o modelo, que propõe os próximos
  requisitos, guardados versão por versão. Todo número, data ou achado que o texto afirma cita o seu
  fato como uma nota de rodapé numerada, e **Evidência** lista o que cada uma é: um resultado com o
  seu status, nota e horário, um evento com o seu horário e resumo, ou as contagens do período. Uma
  tag ou data que os fatos não dão é sinalizada, e a citação de um fato que o modelo não recebeu é
  descartada. A seção fica desligada até um administrador atribuir um modelo aos usos `report-write`
  e `report-tune`.

Mova as seções para cima e para baixo; painéis e eventos podem ter **meia largura**, e duas seções
de meia largura seguidas ficam lado a lado. Enquanto você edita, os painéis leem com o seu próprio
acesso; o PDF lê com o do View, como um dashboard publicado.

## Gerar, baixar e enviar

- **Baixar** lê o relatório agora e o salva no seu computador; ninguém mais o recebe:
  - **PDF**: para imprimir e guardar; ele também fica em **Enviados**.
  - **Word (.docx)**: para alterar e repassar. Os títulos são os próprios Título 1 a 4 do Word, as
    tabelas são tabelas do Word, os gráficos são imagens. Abre no Word, no LibreOffice e no Google
    Docs.
  - **Página web (.html)**: um arquivo que abre em qualquer lugar, offline: as seções ao lado, e
    gráficos que mostram o valor de cada linha sob o ponteiro (como o Grafana faz); clique em uma
    linha da legenda para ocultá-la.
  - **Markdown (.md)**: texto simples para uma wiki, um notebook ou um chamado: o texto como escrito
    e cada painel como os seus valores.
- **Enviar agora** o gera e o envia aos destinatários, como a agenda faria.
- **Enviados** lista todos os PDFs gerados: quando, o que cobriu, como (agendado, enviado,
  baixado), quantas pessoas alcançou, e se uma seção não pôde ser lida. Uma seção que não pode ser
  lida diz por que no PDF e o resto do relatório ainda é gerado; um relatório que não pode ser
  gerado de jeito nenhum é um envio com falha, e os administradores da plataforma são avisados.

## Links públicos

**Compartilhar** cria um link que abre o relatório como a sua página web, lida de novo a cada vez
que é aberta, sem entrar: para um colega sem conta ou uma tela. Um link abre só aquele relatório e
para de funcionar quando é revogado ou o relatório é excluído (veja *Links públicos*).

## Pastas

Relatórios e dashboards compartilham as mesmas pastas, que dizem quem vê e quem edita o que elas
contêm; **Nova pasta** está nas duas páginas. **General** não é uma pasta: guarda o que está fora de
todas as pastas, aberto a todos, por isso não tem configurações e nenhuma pasta pode ter o nome
dela. A cópia de um relatório começa sem agenda, assim nunca envia duas vezes o que o original
envia.
