# Conceitos

As palavras que o PlantCraft e os apps da suíte compartilham.

### Fonte

Um sistema de onde vêm os dados da planta: um servidor OPC UA com acesso ao
histórico, uma PI Web API ou um arquivo CSV. O arquivo de cenário indica uma;
administradores adicionam outras no app **Historian**. As senhas são
criptografadas no servidor.

### Sinal

Uma tag de uma fonte (um NodeId no OPC UA, um ponto no PI, uma coluna no CSV)
com nome e unidade de engenharia. Um sinal **em uso** é um que a suíte acompanha
e que os apps podem ler.

### Ativo

Uma pasta da planta: site, unidade, área, equipamento, malha ou um tipo seu. Os
ativos formam uma árvore, e cada um pode ter sinais vinculados.

### Papel

Para que um sinal serve no seu ativo: `pv`, `sp`, `op`, `mode` e `secondary`
numa malha, ou qualquer palavra (`pressure`, `vibration`...) em outros ativos.

### Malha

Um ativo do tipo `loop` cujos sinais têm papéis de malha. O PlantCraft guarda
a malha e seus sinais; um app como o Analytics decide como analisá-la.

### Grupo

Pessoas que trabalham juntas: um departamento, área, disciplina ou equipe. Os
grupos formam uma árvore; uma pessoa pode estar em vários, e o coordenador de um
grupo o lidera e vê as ações dos grupos abaixo. Uma ação pode ir para um grupo,
e todo grupo tem a sua conversa.

### Origem

De onde um ativo veio: do arquivo de **cenário**, de um **mapa** da planta ou
de uma pessoa (**manual**). Uma sincronização nunca altera nem remove o que uma
pessoa fez.

### App

Um programa da suíte instalado ao lado do PlantCraft (`PLANTCRAFT_APPS`).
Cada pessoa pode abrir todos os apps ou só alguns.

### Nível de acesso

Administrador, editor, leitor ou só painéis: o que uma pessoa pode alterar,
aqui e nos apps.

### Token e chave de app

Um token prova a um app quem você é; dura minutos e se renova enquanto o
PlantCraft está aberto. Uma chave de app permite que um app trabalhe sozinho;
ela aparece uma única vez e pode ser revogada.

### Registro de auditoria

O registro de quem alterou o quê, escrito pelo PlantCraft e pelos apps.
