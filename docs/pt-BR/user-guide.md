# Guia do usuário

O PlantCraft é onde você entra na suíte. Ele guarda o que todos os apps
compartilham: as pessoas, seus grupos e o que cada uma pode abrir, a árvore de
ativos, as ações e as mensagens. Os apps da suíte (o Historian para os dados da
planta, Analytics, Alarms, Models, Dashboards) abrem pelo menu. Nada na suíte altera
o processo: ela só lê os sistemas da planta.

## Entrar

Com o login ativo, informe seu usuário e senha (peça ao administrador, que os
cria em **Usuários**). Um app da suíte que
precisa que você entre manda você para cá e, depois do login, leva você de
volta para onde estava. A demonstração não tem senha: o menu de perfil, no
canto inferior esquerdo, troca de pessoa.

## Acesso

O que você pode fazer depende do seu nível de acesso e dos apps liberados para
você:

- **Administrador**: tudo, inclusive pessoas, grupos, apps e Settings.
- **Editor**: altera a árvore de ativos e edita nos apps.
- **Leitor**: vê os ativos e abre seus apps somente para leitura; não altera
  nada, e os botões de criar e editar não aparecem.
- **Só painéis**: para telas da sala de controle.

Um administrador também pode limitar você a uma parte da planta (uma unidade, uma área): então a
árvore de ativos começa nesses ativos, e você vê só os sinais deles, o que os apps dizem sobre
eles e as ações sobre eles.

## Desk: o seu dia

Ao entrar você chega no **Desk**, o seu espaço de trabalho. **Hoje** é uma página de
widgets que você organiza: **Próximos dias** (o que tem data, como o widget de
calendário do celular), **Minhas actions** (suas, dos seus grupos ou as que você
criou), **Notificações** (as não lidas: alarmes, execuções e mudanças nas suas
actions), **Checklist de hoje**, **Sugestões para hoje** (cada uma com o seu
motivo; aceite, adie ou dispense), **Ativos que sigo** e, para o líder de um grupo,
**Minha equipe**. Cada app instalado acrescenta os seus widgets. **Personalizar**, no
canto superior direito, permite arrastar um widget pelo título, puxar o canto para
mudar o tamanho, configurá-lo (a engrenagem) e pôr o mesmo widget duas vezes com
outras configurações; cada pessoa guarda a sua organização.

As outras páginas do Desk: **Ações**, **Calendário** (mês, semana ou
lista; arraste uma action para mudar o prazo; **Adicionar um calendário** importa um
arquivo `.ics` do Outlook ou do Google, ou lê pelo link quando um administrador
permitiu em Configuração › Calendários), **Rotinas** (listas que põem seus itens no
checklist todo dia, em dias úteis ou em dias escolhidos; um líder pode definir uma
para o grupo todo) e **Equipe**. **Seguir**, na página de um ativo, traz os alarmes e
resultados dele para o seu Desk.

**Mensagens** e o **Assistente** ficam embaixo do menu, acima do seu nome, em todos os
apps: cada um abre por cima da página em que você está, e ao fechar você volta para ela.
Mensagens tem duas seções: **Conversas**, com pessoas e grupos, e **Notificações**, lidas
como uma caixa de e-mail (alarmes, execuções e mudanças que outras pessoas fizeram nas
suas actions; abra para ler e arquive quando estiver resolvida).

## PlantCraft e os apps

O **PlantCraft**, último na lista de apps, é a configuração da suíte: a **Visão
geral** responde "a instalação está saudável?", em widgets que você organiza: **Apps online**,
**Conexões de dados** (cada conexão do Historian), **Sistema** (problemas abertos, disco livre,
último backup, versão, quem entrou hoje) e, para administradores, **Últimas mudanças** da
auditoria. **Personalizar** traz os outros de volta: **Precisam de atenção**, **Ações abertas**,
**Piores primeiro**, **Seus apps** e os widgets de cada app instalado (um app que não está
instalado não acrescenta nada). Um quadro que você organizou fica como está; **Restaurar o
padrão** traz este. Ativos, Configuração, Usuários, Apps e
Operações são páginas do PlantCraft.

## Navegação

Todo app da suíte tem o mesmo menu à esquerda: as páginas do app, depois
**Apps** (todos os apps que você pode abrir: o Desk primeiro, depois na ordem em
que o dado passa: Historian, Analytics, Models, Alarms, View, e o PlantCraft por último;
um clique troca de app). Seu nome,
embaixo, abre o menu do usuário: tema claro, escuro ou do sistema (uma escolha
para todos os apps), o idioma, **Ajuda**, **Fazer o tour**, **Sobre** (a versão) e
**Sair**; um clique fora fecha o menu. **Recolher** deixa o menu só com ícones.

## Fontes e sinais

As fontes da planta (OPC UA, PI Web API ou CSV), seus sinais e o histórico
ficam no app **Historian**: adicione e teste uma fonte, navegue pelas tags,
escolha os sinais a guardar e por quanto tempo. Um sinal na página de um ativo
abre lá.

## Ativos

**Ativos** mostra a planta em pastas: site, unidades, áreas, equipamentos e
malhas, cada um com seus sinais. **Importar** e **Exportar** (no alto da
página) movem só a árvore: ativos, suas fichas, os sinais que referenciam e suas
relações, em JSON do PlantCraft, Excel, CSV, ISA-95 B2MML ou PI AF XML. Uma
importação abre antes uma página de conferência: o arquivo em árvore, cada ativo
marcado como novo, alterado, sem mudança ou com erro, onde você corrige nome,
tipo ou lugar, ou tira uma linha, antes de aplicar. **Copiar como prompt**, na
página de importação, explica o arquivo ao seu assistente de IA, para ele montar
a árvore a partir dos documentos da planta ou da exportação de outro sistema.
Fontes e malhas entram pelo arquivo de configuração (Configuração). Um sinal pode ser referenciado por vários ativos
(a PV de uma malha é também a medição do seu transmissor); a aba **Sinais** de
cada ativo mostra onde mais seus sinais são usados. Busque por nome ou código, filtre por tipo,
crie um ativo (administradores), mova-o para dentro de outro ou adicione um
tipo seu. Uma malha é um ativo cujos sinais têm os papéis `pv`, `sp`, `op`,
`mode` e `secondary`; os apps que analisam malhas as leem daqui. Um ativo que
você editou à mão nunca mais é alterado pelo arquivo de cenário nem por um
mapa.

A página de um ativo fica em `/assets/<id>` (por exemplo `/assets/FIC-101`);
copie o endereço para compartilhá-la. Links antigos `/plant/<id>` continuam
abrindo a página. Suas abas: **Visão geral** (o cadastro ao lado dos sinais
principais e do que há dentro), **Sinais** (uma tabela: cada papel do tipo e o
sinal que o preenche, ou a lacuna a vincular, depois os outros sinais, com o
último valor), **Dentro** (tudo abaixo dele), **Relações**, **Ações** e
**Histórico**. A aba fica no endereço (`?tab=signals`).

## Ações

**Ações** é um quadro com uma coluna por status (aberta, em andamento,
bloqueada, concluída); cada cartão diz há quanto tempo está ali e o prazo.
Editores arrastam um cartão para outra coluna para mudá-lo; o que já terminou e
deve sair do quadro fica **Arquivada**. O cartão mostra o título, o começo da
descrição e o andamento do checklist. **Lista** mostra as mesmas ações em
tabela. Um cartão abre a página da ação: descrição, um **checklist** (itens
marcados um a um, cada um com responsável e prazo), sobre o que é, histórico e
comentários, e os dados ao lado. Escreva `#` (ou use **Mencionar**) para apontar
um ativo, uma pessoa ou uma execução: vira link. O nome de uma pessoa abre a
página dela.

Uma ação vai para uma pessoa, para um grupo ou para os dois. Cada pessoa vê as
ações que tem, que criou ou em que foi mencionada, as dos seus grupos e, quando
lidera um grupo, as dos grupos abaixo dele; o administrador vê todas.
**Exibir** escolhe o que o quadro lista: **Todas que posso ver**, **Atribuídas
a mim**, **Dos meus grupos** ou **Criadas por mim**; filtre por grupo, pessoa,
status ou texto no alto.

## Mensagens

**Mensagens** guarda conversas entre pessoas e com especialistas. **Nova
conversa** escolhe as pessoas uma a uma, ou um grupo inteiro de uma vez. Todo
grupo tem também a sua conversa (**Conversa do grupo** na página do grupo): os
participantes são os do grupo e acompanham o grupo quando alguém entra ou sai.

Todo nome abre a página da pessoa: cargo, setor, unidade, como falar com ela e
as ações que ela tem. **Meu perfil**, no menu do usuário, é onde cada pessoa
mantém o seu.

**Tipos de ativo**, uma aba de **Ativos**, diz o que cada tipo de ativo registra:
atributos, papéis de sinal e o que pode ficar dentro dele (os administradores
editam).

## Pessoas e grupos (administradores)

**Usuários › Grupos** guarda a organização como uma árvore: departamentos,
áreas, disciplinas e equipes, cada um abaixo de outro. O coordenador de um grupo
é o seu líder e vê as ações de todos os grupos abaixo dele. Uma pessoa pode
estar em vários grupos; escolha-os na página do grupo ou na conta da pessoa.

## Pessoas e chaves de app (administradores)

Em **Usuários** e **Apps › Chaves de app**:

- cadastre uma pessoa com usuário, senha inicial, nível de acesso e os apps que
  ela pode abrir (ou todos, inclusive os instalados depois);
- dê a uma pessoa outro papel num app específico (só leitura no Historian,
  edição em Alarmes) diferente do nível, e preencha o perfil dela;
- limite uma pessoa, ou todos os membros de um grupo, a uma parte da planta: em **Ativos que a
  pessoa vê** (ou **Ativos que os membros veem**, no grupo) escolha as unidades ou áreas; ela vê
  esses ativos, tudo abaixo deles, os sinais deles e o que os apps dizem sobre eles;
- mude o nível ou os apps de uma pessoa (vale na hora), redefina a senha (as
  sessões abertas terminam) ou desative-a (o histórico fica);
- emita uma **chave de app** para cada app da suíte. O app a usa no trabalho em
  segundo plano, como as rondas do Analytics. A chave aparece uma única vez:
  copie-a para a configuração `PLANTCRAFT_APP_KEY` do app. Revogue uma chave
  quando ela vazar ou o app mudar de lugar.

## Configuração (administradores)

A **Configuração** guarda o que não tem outro lugar: o **Arquivo de configuração** (as
fontes, os sinais, os ativos e as malhas de uma instalação de uma vez; veja
[Arquivo de configuração](configuration-file.md)), o **Login corporativo**, os
**Modelos de linguagem**, o acesso de assistentes (MCP), o e-mail e os backups.
Pessoas, grupos e especialistas ficam em **Usuários**; apps e chaves de app em
**Apps**; tipos de ativo em **Ativos**.

## Modelos de linguagem e especialistas (administradores)

Especialistas são usuários robô a quem as pessoas mandam mensagens; respondem com o que os
apps publicaram. Sem modelo de linguagem, respondem por roteiro. Em **Configuração › Modelos
de linguagem** o administrador adiciona os servidores onde os modelos rodam: um nome, o
formato (compatível com OpenAI para Ollama, vLLM, LM Studio, Azure e a maioria dos gateways,
ou Anthropic), o endereço, a chave se o servidor pedir e a lista de modelos que ele oferece.
Cada modelo tem um botão **Testar**. Um provedor e modelo é o padrão da instalação, e nada é
enviado a lugar nenhum até "Usar modelos de linguagem" estar ligado. Em **Usuários ›
Especialistas** cada especialista responde com o padrão, com um provedor e modelo escolhidos
para ele, ou só por roteiro.

## Demonstração

Uma instalação feita com `install.sh --demo` (ou `--public-demo`, que também
abre uma conta `demo` somente leitura na página de entrada) roda o Simulator,
uma planta simulada de 50 malhas lida por OPC UA, e uma história de
demonstração em todos os apps: malhas com válvula agarrando, oscilação e sensor
derivando no Analytics, alarmes, dashboards, gêmeos, modelos, ações e conversas. Para
gravar a história de novo (nunca duplica nada), rode na pasta da instalação:

```bash
docker compose exec processcraft plantcraft demo seed
```

A partir do código-fonte, `python run_opcua_demo.py` inicia a mesma
demonstração para desenvolvimento (veja o README).
