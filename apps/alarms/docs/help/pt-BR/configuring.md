# Regras

Uma regra diz **onde** se aplica, **quando** dispara, **o que gera**, para onde vão seus alarmes
(**saídas**) e **por quê**. Cada regra se lê como uma frase na sua página e na lista.

## Onde

- **Ativos** nomeados, todos os ativos **sob** um ramo do mapa da planta, ou todos os ativos de
  um **tipo**, os de hoje e os adicionados depois.
- Os ativos de um **monitor do Analytics** (aquilo em que ele roda).
- **Em qualquer lugar**: qualquer ativo que os eventos da regra citem.
- **Nada**: uma regra só sobre valores ou eventos nomeados, com um alarme.

**Um alarme por** ativo (o padrão), por monitor, ou um para a regra inteira.

## Quando: Simples ou Python

- **Simples**: até três condições unidas por **e** ou **ou**. Uma condição lê um **valor**
  (acima, abaixo, entre, fora, mudou, ou **não mudou**: uma medição congelada) com uma **banda
  morta**, ou um **evento** (aberto por pelo menos tanto tempo, ou contado tantas vezes em uma
  janela). Ela pode precisar valer **por pelo menos** tantos minutos ou valores, e o alarme
  normaliza **após** tanto tempo de volta ao normal.
- **Python**: para qualquer outra lógica. Escolha alguns valores como entradas; `check(inputs)`
  lê a última leitura de cada um (`inputs.flow`, None quando não há dados) e responde
  `True, "frase"` para disparar ou `False, ""` para não disparar. O editor começa a partir de um
  exemplo comentado para as entradas, mostra o que entra e o que sai ao lado do código, e abre em
  tela cheia com **Ampliar**. Só administradores escrevem código; ele roda na área isolada do
  PlantCraft (sem rede, sem arquivos, com tempo e memória limitados), no máximo uma vez por
  minuto.

Uma regra desenhada no antigo editor de Blocos continua rodando como foi desenhada (as que
cabiam foram reescritas como Simples ou Python); para alterar sua lógica, escreva-a de novo em
Simples ou Python.

Os valores e eventos são escolhidos no **Explorer**: o mapa da planta com os sinais de cada
ativo, as séries que os apps calcularam sobre ele e os eventos que o citaram. Um valor escolhido
para **cada ativo** é lido em todos os ativos da regra.

### Só enquanto: alarmes que dependem do estado da planta

**Só enquanto…** no formulário Simples adiciona uma permissiva: uma condição de valor que precisa
valer para que o alarme seja avaliado (alarme baseado em estado, supressão por projeto da
ISA-18.2). Um alarme de vazão baixa **só enquanto P-101 funcionando ≥ 1**, com **Habilitado
após** 30 s para que a vazão se acomode depois de uma partida. Enquanto a permissiva não vale, o
alarme fica suprimido por projeto: não dispara, normaliza se tiver disparado, e sua página diz
isso. Uma permissiva que não pode ser avaliada (sem dados) deixa o alarme habilitado, para que um
sinal ruim nunca esconda um alarme. Em Blocos, é a entrada **Habilitado quando** de Disparar um
alarme.

### Limites por grade: um limite para cada produto

Uma linha que produz várias grades costuma precisar de um limite diferente para cada uma. Um
alarme de índice de fluidez, por exemplo, pode ficar em 50 para a grade HD-5 e em 90 para a LD-2.

1. No formulário Simples, escolha **Limites por grade…**.
2. Diga de onde vem a grade em produção:
   - **Um sinal** que contém o código da grade. O código 3 é a grade "3".
   - **Um evento**: o evento mais recente dos tipos que você escolher indica a grade, em um campo
     do payload (`grade` por padrão). O `mes.grade.changed` de um MES é um exemplo.
3. Em cada condição comparada com um limite, liste as grades com seus limites.

O limite acima continua valendo em dois casos: antes de qualquer grade ser conhecida, e para uma
grade que a lista não cita. A página do alarme diz qual grade e qual limite se aplicam. O Alarms
guarda a última grade entre as verificações, então um evento de troca de grade só é necessário
uma vez.

Em Blocos, isto é um bloco **Limite por grade** conectado à entrada **Limite** de um Comparar.

## O que gera

- **Um alarme**: precisa de reconhecimento, aparece no Alarms e conta em Desempenho (ISA-18.2).
- **Um alerta**: aparece no Alarms e é enviado, mas não precisa de reconhecimento e fica fora de
  Desempenho. Bom para o que os apps reportam sobre si mesmos, como uma execução que falhou.

A **prioridade** é crítica, alta, média ou baixa; mantenha a maioria das regras em baixa.
**Responsável**, **área** e **disciplina** dizem quem responde por ela e onde ela está; a área
vem da árvore de ativos quando deixada vazia. A **racionalização** é a causa, a consequência de
não agir e a ação corretiva: um alarme sem uma ação para o operador não deveria ser um alarme.

## Saídas

- **Alarms**: sempre; o alarme é listado para reconhecer, suprimir e comentar.
- **Dashboards** (ligada): seus alarmes colorem seus ativos e aparecem nos widgets de alarmes
  ativos do View e da Visão geral.
- **Mensagens** (ligada, para o responsável): nas Mensagens do PlantCraft, agrupadas, com
  lembretes, horários e escalonamento. Veja **Notificações**.
- **E-mail**: aparece depois que um administrador configura o servidor de e-mail do PlantCraft
  (Configurações, E-mail); vai para as pessoas que permitem isso no seu perfil.

## Testar antes de salvar

**Testar** roda a regra, como está escrita, sobre os últimos dias de valores e eventos e diz
quantos alarmes ela teria gerado, em quantos alvos, e cerca de quantas mensagens teria enviado
depois de agrupadas. Se uma regra dispararia dezenas de vezes por dia em operação normal, seu
limite, banda morta, atraso ou contagem precisa de ajuste.

## Desligar uma regra

**Desligar** na página da regra a interrompe: seus alarmes ficam fora de serviço até ela ser
ligada. Excluir uma regra encerra seus alarmes; o diário deles fica. Alterar a lógica de uma
regra encerra seus alarmes ativos e volta a avaliar dali em diante.

## Importar a lista de alarmes do SDCD

**Importar lista de alarmes** em Regras lê a lista de alarmes exportada do SDCD (a base mestra de
alarmes): um arquivo CSV, ou Excel salvo como .xlsx. **Modelo** fornece um arquivo com as colunas
que o Alarms lê. Cada linha é um alarme sobre um sinal:

- **tag** (o sinal, pelo seu id ou pelo seu nome no SDCD, como `FIC-1001.PV`) e **type**: HH,
  HI, LO ou LL (PVHI, HIHI, LOLO e similares também são lidos);
- **limit** e, opcionalmente, unidade, **priority** (critical, high, medium, low, ou de 1, a mais
  urgente, a 4), banda morta, atraso na ativação (segundos, `2 min` ou `00:00:10`), descrição,
  causa, consequência, ação e habilitado.

Ler o arquivo não altera nada. A revisão lista o que uma aplicação faria: regras **novas**,
**alteradas** (campo a campo, antes e depois), **removidas** (alarmes que uma importação
anterior criou e que a lista não tem mais) e linhas que não puderam ser lidas, com o número da
linha. Desmarque o que não deve mudar e clique em **Aplicar**. A regra de um alarme removido é
desligada, nunca excluída. O que as pessoas definiram no próprio Alarms (onde, quem é
notificado, responsável, área) fica. Uma regra que alguém alterou depois que o arquivo foi lido
fica como está e é listada: leia o arquivo de novo para vê-la. As regras escritas à mão nunca
são tocadas. Cada importação é casada alarme a alarme pela tag e pelo tipo.
