# Documents

O Documents guarda os documentos da planta em um só lugar: manuais de operação, descritivos de
controle, P&IDs, folhas de dados, procedimentos, guias de solução de problemas, registros de
manutenção e relatórios de incidente. Ele lê cada arquivo, para que você e o assistente encontrem o
trecho que responde a uma pergunta, com a sua página.

## Visão geral

O Documents abre na **Visão geral**: uma caixa de busca (palavras ou uma pergunta; ela abre
**Buscar** com o que você digitou), quantos documentos estão prontos para busca e quantos estão em
leitura, os documentos mais recentes (com quando cada um foi enviado ou alterado) e os que ninguém
vinculou ainda aos ativos da planta. Enquanto os arquivos são lidos, uma linha acima dos widgets diz
quantos. **Personalizar** organiza os widgets; **Biblioteca**, no menu, abre as pastas e todos os
documentos.

## Enviar um documento

Na **Biblioteca**, escolha uma pasta na coluna à esquerda e clique em **Enviar arquivos** (ou solte
os arquivos na página). A linha abaixo do título diz o que é lido: PDF, Word (.docx), Excel (.xlsx),
PowerPoint (.pptx), texto, Markdown, CSV e HTML, até 200 MB por arquivo. Arquivos .doc, .xls e .ppt
antigos não são lidos: salve-os no formato novo antes.

- Dê ao documento o **número** (DOC-U200-OM-001), o **título**, uma **descrição** (o que abrange,
  para quem; a busca e o assistente também a leem), o **tipo** e a **unidade**. Um arquivo enviado
  com um número que já existe vira a **nova revisão** dele; a revisão anterior fica no histórico do
  documento e deixa de ser buscada.
- O arquivo é lido em segundo plano, de alguns segundos a alguns minutos: a **Fila** da barra
  lateral lista os arquivos esperando, em leitura e lidos no último dia. Um arquivo que não pode
  ser lido diz por quê (por exemplo, um PDF digitalizado sem texto).
- As tags encontradas no texto (FIC-1003, FV-1003, P-1003) que existem na árvore de ativos do
  PlantCraft são **sugeridas** como ativos do documento. Confirme-as na página do documento: o
  assistente coloca em primeiro lugar um documento vinculado a um ativo quando você pergunta sobre
  esse ativo.
- **Vínculos a verificar** (na Biblioteca, se você pode editar) lista os ativos encontrados no texto
  de todos os documentos que você pode alterar. Escolha vários e marque-os como **Correto**, para
  vinculá-los, ou **Errado**, para que não sejam sugeridos de novo. Um administrador pode definir um
  número de menções a partir do qual um ativo é vinculado na hora (`DOCCRAFT_ASSET_AUTO_MENTIONS`,
  desligado por padrão).

## Encontrar algo

**Buscar** encontra trechos pelas palavras e pelo sentido, em inglês e em português: "por que a
vazão de reciclo salta?" encontra o trecho sobre agarramento (stiction) de válvula mesmo quando ele
nunca diz "salta". Filtre por tipo ou por ativo. Cada resultado mostra a parte do trecho em torno
das suas palavras, com as palavras em negrito, e abre o documento nesse trecho, marcado, com as suas
palavras em negrito de novo. **Abrir o PDF**, em um PDF, abre naquela página; **Abrir o documento**,
em um arquivo Word, o mostra como página (o texto, os títulos e as tabelas). Ctrl+K, em qualquer
lugar da suíte, encontra documentos por número ou título e os melhores trechos.

## Diagramas e o mapa da planta (beta)

Os P&IDs enviados à biblioteca também são lidos como desenhos, offline e sem modelo de linguagem.
Isso funciona para PDF de uma ferramenta CAD, SVG e digitalizações ou imagens (PNG, JPEG, TIFF). A
exportação DEXPI (XML) de uma ferramenta de P&ID é lida com exatidão: a ferramenta já diz o que é
cada item e o que liga ao quê, então nada ali é palpite. Toda página que é um diagrama é listada em
**Diagramas**. Cada página abre com caixas sobre o que foi encontrado e uma lista do que verificar
primeiro. Cada achado diz quanta certeza o leitor tem e por quê. Escolha uma caixa: se o PlantCraft
tem aquela tag, o ativo, os sinais dele e o que os apps dizem sobre ele ficam a um clique.

**Mapa da planta** junta todas as folhas em uma planta:

- as unidades, com os equipamentos na ordem do fluxo e as malhas de controle em cada um;
- as linhas de uma folha para outra, pelos conectores de continuação;
- as válvulas manuais desenhadas sem tag: um pequeno círculo em uma interrupção de uma linha (uma
  válvula esfera ou manual como as ferramentas DIN/ISO 10628 a desenham) é uma válvula pela qual a
  linha passa;
- um resumo e a lista **A verificar**.

No mapa, você pode trabalhar com o que foi lido:

- Escolha um item para ver as linhas dele e as folhas em que ele está desenhado. Se o PlantCraft já
  o tem, o cartão dele abre o ativo, os sinais dele e o que os apps da suíte dizem sobre ele.
- **Correto** ou **Errado** em qualquer item ou linha, se você pode editar. Errado o tira do mapa e
  de todas as exportações. **Desfazer** o traz de volta.
- **Listas** baixa as listas de equipamentos, instrumentos, linhas e malhas em CSV.
- **DEXPI (XML)** baixa o mapa no formato aberto de troca de P&IDs, para ferramentas como AVEVA,
  Hexagon Smart P&ID ou COMOS. Ele contém os equipamentos, as linhas e as malhas de instrumentos,
  sem o desenho.
- **Arquivo de ativos** vai para Ativos › Importação do PlantCraft, onde você o revisa antes que
  algo mude.
- **Escrever o resumo da planta** (se você pode editar) escreve o mapa como um documento da
  biblioteca, na pasta que tem a maioria dos P&IDs. Ele cobre cada unidade, os equipamentos na
  ordem do fluxo com o que alimenta o quê, as malhas de controle e as folhas em que cada item está
  desenhado. Ele é feito a partir dos desenhos, sem modelo de linguagem. A busca e o assistente o
  encontram e o citam como qualquer outro documento. Faça de novo depois de uma mudança: ele vira
  uma nova revisão.
- **Conferir com uma lista de tags**: escolha a lista de tags da sua planta (CSV ou texto, com a tag
  na primeira coluna) para ver quais tags estão em ambos e quais estão só em um. O arquivo fica no
  seu navegador.

Em uma digitalização, um editor também pode escolher **Ler de novo com o modelo de linguagem** na
página do diagrama. A imagem da página e o que foi encontrado nela vão para o modelo que um
administrador escolheu para "Read a scanned diagram again" em Instalação › Modelos de linguagem
(desligado até lá). O que o modelo acrescenta é marcado como do modelo, com certeza média:
confira-o no mapa.

A qualidade da leitura depende do desenho:

- Um P&ID vetorial limpo é lido quase por completo.
- Em uma digitalização, as tags são lidas, mas as linhas não.
- Em um P&ID de uma ferramenta comercial, as tags são bem lidas, mas só parte das linhas.

Então confira as linhas antes de usá-las.

## Perguntar ao assistente

O assistente busca e lê os documentos que você pode abrir e cita cada fato como [n], com o
documento, a revisão e a página; cada [n] abre o documento naquele trecho. Ele busca nos documentos
a cada pergunta, em todos os apps: em uma página sobre um ativo (uma malha no Analytics, a tag de um
alarme) ele também busca sobre esse ativo. Na página de um documento, ele pode resumi-lo ou
responder só a partir dele; na página de um ativo, ele lista os documentos sobre esse ativo. O
Analytics e o Alarms pedem a ele que consulte os documentos quando procuram a causa de um problema.

## Pastas e quem lê

Uma pasta lista quem a **vê** e quem a **altera** (pessoas e grupos); vazio significa todos com
acesso ao Documents. Um documento em uma pasta que você não pode ver não existe para você: nem nas
listas, na busca, no assistente ou nos links. Desmarque **O assistente pode lê-lo** em uma pasta ou
em um documento para mantê-lo longe do assistente enquanto as pessoas ainda o encontram.

Todo documento enviado, alterado, baixado ou excluído, e toda busca que o assistente faz, fica
registrado no registro de auditoria do PlantCraft.
