# Guia do usuário

O PlantCraft é onde você entra na suíte. Ele guarda o que todos os apps
compartilham: as pessoas, os grupos delas e o que cada uma pode abrir, a árvore
de ativos, as ações e as mensagens. Os apps da suíte (o Historian para os dados
da planta, Analytics, Alarms, Models, Dashboards) abrem pelo menu. Nada na suíte
altera o processo: ela só lê os sistemas da planta.

## Entrar

Com o login ligado, informe o seu usuário e a sua senha (peça ao administrador,
que os cria em **Pessoas**). Um app da suíte que precisa que você entre manda
você para cá e, depois que você entra, leva você de volta para onde estava. A
demonstração não tem senha: o menu de perfil, no canto inferior esquerdo, troca
de pessoa.

## Acesso

O que você pode fazer depende do seu nível de acesso e dos apps liberados para
você:

- **Administrador**: tudo, inclusive pessoas, grupos, apps e Configurações.
- **Editor**: altera a árvore de ativos e edita nos apps.
- **Leitor**: vê os ativos e abre os apps deles somente para leitura; não altera
  nada, e os botões de criar e editar não aparecem.
- **Só dashboards**: para telas da sala de controle.

Um administrador também pode limitar você a uma parte da planta (uma unidade, uma área): então a
árvore de ativos começa nesses ativos, e você vê só os sinais deles, o que os apps dizem sobre
eles e as ações sobre eles.

## Desk: o seu dia

Depois de entrar você chega no **Desk**, o seu espaço de trabalho. **Hoje** é uma página de
widgets que você organiza: **Próximos dias** (o que tem data, como o widget de agenda de um
celular), **Minhas ações** (as suas, as dos seus grupos ou as que você criou),
**Notificações** (as não lidas: alarmes, execuções e mudanças nas suas ações), **Meu dia**
(as tarefas de hoje), **Sugestões para hoje** (cada uma com o seu motivo; aceite, adie ou
dispense), **Ativos que sigo** e **Minha equipe** (o seu grupo: quem está ausente ou tem
trabalho atrasado). Cada app instalado acrescenta os seus widgets. **Personalizar**, no canto
superior direito, permite arrastar um widget pelo título, puxar o canto dele para mudar o
tamanho, configurá-lo (a engrenagem) e adicionar o mesmo widget duas vezes com outras
configurações; cada pessoa guarda a sua própria organização.

As outras páginas do Desk: **Ações**, **Agenda** (mês, semana, dia ou lista; clique ou arraste
para adicionar um evento seu; arraste uma ação para mudar o prazo dela; **Adicionar um
calendário** importa um arquivo `.ics` do Outlook ou do Google, ou o lê pelo link quando um
administrador permitiu em Configurações › Calendários), **Tarefas** (Meu dia, Planejado, as
suas listas e as listas compartilhadas dos seus grupos; uma tarefa tem data, repetição, etapas
e notas, e vira uma ação quando precisa de outra pessoa), **Notas** (privadas até você
compartilhá-las com pessoas ou grupos; títulos, listas, um checklist, `#` para mencionar um
ativo ou uma ação, e uma linha que vira uma tarefa ou uma ação; um evento seu na Agenda tem a
sua própria nota) e **Equipe** (como o seu grupo está hoje: quem está ausente ou ocupado, as
ações do grupo num quadro, a semana que vem e a nota de passagem de turno do dia). **Seguir**,
na página de um ativo, traz os alarmes e resultados dele para o seu Desk.

**Mensagens** e o **Assistente** ficam embaixo do menu, acima do seu nome, em todos os apps:
cada um abre por cima da página em que você está, e fechá-lo traz você de volta. Mensagens tem
duas seções: **Conversas**, com pessoas e grupos, e **Notificações**, lidas como uma caixa de
entrada de e-mail (alarmes, execuções e mudanças que outras pessoas fizeram nas suas ações;
abra uma para lê-la e arquive-a quando estiver resolvida).

## PlantCraft e os apps

O **PlantCraft**, último na lista de apps, é a configuração da suíte: a **Visão geral**
responde "a instalação está saudável?", em widgets que você organiza: **Apps online**,
**Conexões de dados** (cada conexão do Historian), **Sistema** (problemas abertos, disco livre,
último backup, versão, quem entrou hoje) e, para administradores, **Mudanças recentes** do
registro de auditoria. **Personalizar** traz os outros de volta: **Precisa de atenção**,
**Ações abertas**, **Piores primeiro**, **Seus apps** e os widgets que cada app instalado
publica (um app que não está instalado não acrescenta nenhum). Um quadro que você organizou
fica como você o deixou; **Voltar ao padrão** traz este. Ativos, Configurações, Pessoas, Apps,
Saúde do sistema, Backups e Atualizações são páginas do PlantCraft.

## Navegação

Todo app da suíte tem o mesmo menu à esquerda: as páginas do próprio app, depois
**Apps** (todos os apps que você pode abrir: o Desk primeiro, depois na ordem em que os dados
passam: Historian, Analytics, Models, Alarms, View, e o PlantCraft por último; um clique troca
de app). O seu nome, embaixo, abre o menu do usuário: tema claro, escuro ou do sistema (uma
escolha para todos os apps), o idioma, **Ajuda**, **Fazer o tour**, **Sobre** (a versão) e
**Sair**; um clique em qualquer outro lugar o fecha. **Recolher** deixa o menu só com ícones.

## Fontes e sinais

As fontes da planta (OPC UA, PI Web API ou CSV), os sinais dela e o histórico deles ficam no
app **Historian**: adicione e teste uma fonte, navegue pelas tags dela, escolha os sinais a
guardar e por quanto tempo. Um sinal na página de um ativo abre lá.

## Ativos

**Ativos** mostra a planta em pastas: site, unidades, áreas, equipamentos e malhas, cada um com
os seus sinais. A árvore abre no nível 2; **Abrir até o nível** 1, 2, 3 ou Todos, acima dela, a
abre na profundidade de que você precisa (a escolha fica guardada no seu navegador), e
**Recolher tudo** a fecha. **Importar** e **Exportar** (no alto da página) movem só a árvore:
ativos, os registros deles, os sinais que eles referenciam e as relações, em JSON do
PlantCraft, Excel, CSV, ISA-95 B2MML ou PI AF XML. Uma importação abre antes uma página de
revisão: o arquivo como árvore, cada ativo marcado como novo, alterado, sem mudança ou com
erro, onde você corrige um nome, um tipo ou um lugar, ou deixa uma linha de fora, antes de
aplicar. **Copiar como prompt**, na página de importação, explica o arquivo ao seu assistente
de IA, para que ele monte a árvore a partir dos documentos da planta ou da exportação de outro
sistema. **Última importação**, na página de importação, mostra quem importou o quê e quando,
e **Desfazer a última importação** a desfaz uma vez: os ativos que ela criou são removidos e os
registros que ela alterou voltam a ser como eram.

**Rascunhar uma nova planta** (na página de importação, para administradores) escreve a
primeira árvore para você quando ainda não há um arquivo de ativos. Escolha uma fonte (as tags
dela, como o Historian as navega) ou uma lista de tags (`.csv` ou `.xlsx` com uma coluna de tag
e, se você tiver, descrição e unidades de engenharia). Os nomes ISA-5.1 dão cada malha
(`FIC-1003`), os sinais dela por papel (`.PV`, `.SP`, `.OP`, `.MODE`), o tipo dela e o
transmissor e a válvula dela (`FT-1003`, `FV-1003`). Com o **Documents** instalado, as
narrativas de controle, o índice de P&IDs, as folhas de dados e os manuais da planta colocam
cada malha na sua unidade e área, no seu equipamento, com o tipo e o registro do equipamento;
cada linha mostra de onde vem (documento, revisão, página e o trecho). Com um modelo de
linguagem escolhido para **Rascunho da planta** (Configurações › Modelos de linguagem), as
malhas que ainda estão em dúvida são posicionadas pelo modelo a partir dos mesmos trechos; o
que ele citar e as fontes não citarem fica de fora. O rascunho abre na mesma página de revisão:
**Para verificar** filtra as linhas que não estão certas, e deixar de fora uma unidade ou uma
área deixa de fora o que o rascunho pôs nela. Nada é gravado até você aplicar, e a importação
pode ser desfeita.

**Primeiros passos nos apps.** Depois que uma importação é aplicada, a página lista o que cada
app instalado pode começar sobre os ativos que ela gravou: o Historian coleta os sinais deles,
o Analytics monitora as malhas deles (a primeira rodada inicia a linha de base de cada malha),
o Alarms rascunha duas regras por unidade (uma malha em mau estado, um sinal sem dados),
desligadas para você revisar, e o View desenha um dashboard de visão geral por unidade. Marque
os que você quer e aplique-os; cada um é feito como você, com o seu acesso naquele app, e diz o
que fez, com um link para lá. Aplicado de novo depois de uma importação posterior, um passo
pula o que já fez.

Fontes e sinais entram pelo Historian. Um sinal pode ser referenciado por vários ativos (a PV
de uma malha é também a medição do seu transmissor); a aba **Sinais** de cada ativo diz onde
mais os sinais dele são usados. Busque por nome ou código, filtre por tipo, crie um ativo
(administradores), mova-o para dentro de outro ou adicione um tipo seu. Uma malha é um ativo
cujos sinais têm os papéis `pv`, `sp`, `op`, `mode` e `secondary`; os apps que analisam malhas
os leem daqui. Um ativo que você editou à mão nunca mais é alterado pelo arquivo de cenário nem
por um mapa.

A página de um ativo fica em `/assets/<id>` (por exemplo `/assets/FIC-101`); copie o endereço
para compartilhá-la. Links antigos `/plant/<id>` continuam abrindo a página. As abas dela:
**Visão geral** (o registro ao lado dos sinais principais e do que há dentro), **Sinais** (uma
tabela: cada papel do tipo e o sinal que o preenche, ou a lacuna a vincular, depois os outros
sinais, com o último valor), **Dentro de** (tudo abaixo dele), **Relações**, **Ações** e
**Histórico**. A aba fica no endereço (`?tab=signals`).

## Ações

**Ações** é um quadro com uma coluna por estado (aberta, em andamento, bloqueada, concluída);
cada cartão diz há quanto tempo está ali e qual é o prazo. Editores arrastam um cartão para
outra coluna para mudá-lo; o trabalho terminado que deve sair do quadro fica **Arquivado**. Um
cartão mostra o título, o começo da descrição e o andamento do checklist. **Lista** mostra as
mesmas ações como tabela. Um cartão abre a página da ação: descrição, um **checklist** (itens
marcados um a um, cada um com quem e até quando), sobre o que ela é, histórico e comentários,
e os dados dela ao lado. Escreva `#` (ou use **Mencionar**) para apontar um ativo, uma pessoa
ou uma execução: vira um link. O nome de uma pessoa abre a página dela.

Uma ação vai para uma pessoa, para um grupo ou para os dois. Cada pessoa vê as ações de que é
responsável, que criou ou em que foi mencionada, as dos seus grupos e, quando lidera um grupo,
as dos grupos abaixo dele; um administrador vê todas. **Exibir** escolhe o que o quadro lista:
**Todas que posso ver**, **Atribuídas a mim**, **Dos meus grupos** ou **Criadas por mim**;
filtre por grupo, pessoa, estado ou texto no alto.

## Mensagens

**Mensagens** guarda conversas entre pessoas e com especialistas. **Nova conversa** escolhe as
pessoas uma a uma, ou um grupo inteiro de uma vez. Todo grupo também tem a sua própria conversa
(**Conversa do grupo** na página do grupo): os participantes são os do grupo, e acompanham o
grupo quando alguém entra ou sai dele.

Todo nome abre a página da pessoa: cargo, setor, unidade, como falar com ela e as ações de que
ela é responsável. **Meu perfil**, no menu do usuário, é onde cada pessoa mantém o seu.

**Tipos de ativo**, uma aba de **Ativos**, diz o que cada tipo de ativo registra: atributos,
papéis de sinal e o que pode ficar dentro dele (os administradores o editam).

## Pessoas e grupos (administradores)

**Pessoas › Grupos** guarda a organização como uma árvore: departamentos, áreas, disciplinas e
equipes, cada um abaixo de outro. O coordenador de um grupo é o seu líder e vê as ações de
todos os grupos abaixo dele. Uma pessoa pode estar em vários grupos; escolha-os na página do
grupo ou na conta da pessoa.

## Pessoas e chaves dos apps (administradores)

Em **Pessoas** e **Apps › Chaves dos apps**:

- crie uma pessoa com usuário, senha inicial, nível de acesso e os apps que ela pode abrir (ou
  todos os apps, inclusive os instalados depois);
- dê a uma pessoa, num app específico, outro papel diferente do que o nível dela dá (só leitura
  no Historian, edição no Alarms), e preencha o perfil dela;
- limite uma pessoa, ou todos os membros de um grupo, a uma parte da planta: em **Ativos que a
  pessoa vê** (ou **Ativos que os membros veem**, no grupo) escolha as unidades ou áreas; ela vê
  esses ativos, tudo abaixo deles, os sinais deles e o que os apps dizem sobre eles;
- mude o nível ou os apps de uma pessoa (vale na hora), redefina a senha dela (as sessões
  abertas terminam) ou desative-a (o histórico dela fica);
- emita uma **chave de app** para cada app da suíte. O app a usa no trabalho em segundo plano,
  como as rodadas do Analytics. A chave aparece uma única vez: copie-a para a configuração
  `PLANTCRAFT_APP_KEY` do app. Revogue uma chave quando ela vazar ou o app mudar de lugar.

## Configurações (administradores)

**Configurações** guarda o que não tem outro lugar: o **Login corporativo**, o **Registro de
auditoria**, os **Modelos de linguagem**, o acesso de assistentes (MCP), os notebooks, as
agendas e o e-mail. **Saúde do sistema**, **Backups** (com o agendamento deles) e
**Atualizações** têm páginas próprias em Administração. Pessoas, grupos e especialistas ficam
em **Pessoas**; apps e chaves dos apps em **Apps**; tipos de ativo em **Ativos**.

## Modelos de linguagem e especialistas (administradores)

Especialistas são usuários robô a quem as pessoas mandam mensagens; eles respondem com o que os
apps publicaram. Sem modelo de linguagem, respondem por roteiro. Em **Configurações › Modelos
de linguagem** um administrador adiciona os servidores em que os modelos rodam: um nome, o
formato (compatível com OpenAI para Ollama, vLLM, LM Studio, Azure e a maioria dos gateways, ou
Anthropic), o endereço, a chave se o servidor pedir uma e a lista de modelos que ele oferece.
Cada modelo tem um botão **Testar**. Um provedor e um modelo são o padrão da instalação, e nada
é enviado a lugar nenhum até "Usar modelos de linguagem" estar ligado. Em **Pessoas ›
Especialistas** cada especialista responde com o padrão, com um provedor e um modelo escolhidos
para ele, ou só por roteiro.

## Demonstração

Uma instalação feita com `install.sh --demo` (ou `--public-demo`, que também abre uma conta
`demo` somente leitura na página de entrada) roda o Simulator, uma planta simulada de 50 malhas
lida por OPC UA, e uma história de demonstração em todos os apps: malhas com uma válvula com
agarramento, uma oscilação e um sensor com deriva no Analytics, alarmes, dashboards, gêmeos,
modelos, ações e conversas. Para gravar a história de novo (ela nunca duplica nada), rode na
pasta da instalação:

```bash
docker compose exec processcraft plantcraft demo seed
```

A partir do código-fonte, `python run_opcua_demo.py` inicia a mesma demonstração para
desenvolvimento (veja o README).
