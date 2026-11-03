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

## P&IDs

Os P&IDs e o mapa da planta ficam no **PlantCraft PID**, um app separado que um administrador instala
com a sua licença. O Documents guarda os P&IDs enviados como PDF como qualquer outro documento, lidos pelo
texto; desenhos enviados como SVG, DEXPI ou digitalizações vão para o PlantCraft PID.

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
registrado no log de auditoria do PlantCraft.
