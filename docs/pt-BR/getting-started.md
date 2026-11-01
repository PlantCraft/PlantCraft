# Primeiros passos

Uma hora com a planta de demonstração, app por app. Você vai acompanhar um problema, uma
válvula com agarramento, do sinal ao alarme, ao dashboard, a um modelo e a um notebook, e ver
como os apps da suíte o passam um para o outro. É preciso uma instalação com a história de
demonstração (`./install.sh --all-apps --demo`, veja [Instalar o PlantCraft](../install.md)) e a
senha do administrador.

## A planta e a história

A planta de demonstração é o **Simulator**: um servidor OPC UA de 50 malhas de controle em duas
unidades, U-100 e U-200, com falhas que ele simula de propósito. Quatro válvulas agarram
(FIC-1003, FIC-1102, FIC-1206, FIC-1214), algumas malhas de pressão e temperatura oscilam
(PIC-1002, PIC-1202), a temperatura de saída do forno TIC-1209 deriva, e a TIC-1104 sofre uma
perturbação cíclica.

A história preenche a suíte como se uma equipe a tivesse usado por três semanas: Ana Lima, a
engenheira de processo, um técnico, operadores e um supervisor, as conversas e as ações deles,
monitores já em execução, dashboards, regras de alarme, estudos de modelos e as conversas com o
assistente que eles guardaram. O visitante da demonstração participa das conversas da equipe em
Mensagens.

## 1. Entrar e encontrar o seu dia (Desk)

Abra o endereço da suíte e entre como `admin`. Você chega no **Desk**, o dia de cada pessoa:

- **Hoje** reúne o que precisa de você: notificações, ações atribuídas a você, os eventos do
  dia e os widgets que você escolhe. **Personalizar** move e adiciona widgets.
- **Ações** guarda os acompanhamentos que a equipe abriu, como *Inspect the FIC-1003 recycle
  valve for stiction*. Abra uma para ver o alvo, o responsável e o histórico dela.
- **Agenda**, **Tarefas**, **Notas** e **Equipe** são o resto do dia: reuniões, a sua própria
  lista, notas e quem está no turno.

Embaixo da barra lateral ficam os quatro botões rápidos que todo app compartilha: **Mensagens**
(conversas com pessoas e especialistas), **Notificações** (o que precisa de uma pessoa),
**Assistente** (a conversa com IA da página em que você está) e **Fila** (o que está rodando em
segundo plano, app por app).

## 2. O mapa da planta (PlantCraft)

Abra o **PlantCraft** no menu de apps, depois **Ativos**. A árvore é a planta: o site, as
unidades dele, áreas, equipamentos e malhas. Abra a **FIC-1003**: os sinais dela estão listados
por **papel** (o `pv`, o `sp` e o `op` da malha), então todo app sabe qual sinal é a medição e
qual é a saída para a válvula sem que ninguém precise dizer de novo.

Todo app lê a mesma árvore. Quando você adiciona uma unidade ou uma malha aqui, o Analytics, o
Alarms e o View a veem na hora. Um mapa inteiro da planta pode ser carregado de Excel ou JSON
([Arquivo de configuração](configuration-file.md)).

## 3. Os dados (Historian)

Abra o **Historian**. **Fontes** lista de onde vêm os dados: aqui, o servidor OPC UA do
Simulator; numa planta, uma fonte PI Web API, OPC UA, MQTT, Modbus TCP, SQL ou CSV. **Sinais**
lista todos os sinais arquivados, com as configurações de varredura e compressão de cada um.
Abra `FIC-1003.OP` e veja um dia dele: a saída para a válvula se move em degraus em vez de
suavemente, o primeiro sinal de agarramento.

O Historian só lê da planta. **Sinais calculados** derivam novos sinais de outros (uma
diferença, uma razão, um filtro), **Importações** traz arquivos uma vez ou toda vez que eles
chegam numa pasta, e **Exportações** leva dados para CSV.

## 4. Acompanhar as malhas (Analytics)

Abra o **Analytics**. Ele executa **algoritmos**, feitos de **blocos**, sobre os ativos e os
sinais da planta, e publica **resultados**: um nível (OK, Atenção, Crítico ou Desconhecido),
uma pontuação de 0 a 100 e uma frase que diz por quê.

1. **Monitores** lista o que roda sozinho: *Desempenho de malhas de controle* julga cada malha,
   *Qualidade dos sinais* cada sinal, e *Furnaces* executa o modelo dos fornos ao lado da
   planta.
2. **Resultados** mostra o que eles concluíram, por monitor, depois por alvo, depois ao longo do
   tempo. Abra a FIC-1003: o resultado dela aponta agarramento e mostra as evidências, a
   tendência e a assinatura da válvula.
3. **Algoritmos** mostra como se chega a um resultado. Abra *Flow loop* e o editor o desenha
   como blocos ligados entre si. **Testar** o executa numa malha agora, sem salvar nada;
   **Copiar como prompt** o transforma num prompt para revisá-lo ou estendê-lo com qualquer
   assistente de IA.
4. O modelo do forno também é um algoritmo: um modelo de processo ao lado da planta que diz
   quando a TIC-1209 medida se afasta do que o modelo prevê.

O Analytics nunca mexe na planta. Ele lê, julga e diz, e quando não consegue julgar (um sinal
congelado, uma lacuna, movimento de menos) diz Desconhecido e por quê, em vez de adivinhar.

## 5. Alarms

Abra o **Alarms**. As **Regras** transformam sinais e resultados do Analytics em alarmes e
alertas, nas palavras da ISA-18.2: uma regra é **Simples** (um limite com banda morta e
atraso), **Blocos** ou **Python**. Abra *PIC-1202 pressure high* ou *Loop critical for over 1 h*
para ver cada tipo.

- **Alarmes** é a lista do que está ativo agora. **Reconhecer** reconhece um; **Suprimir** o esconde por
  um tempo, com um motivo. Um alarme também chega em **Notificações**, com os mesmos botões.
- **Eventos** lista o que os apps publicaram (um resultado que mudou de nível, uma execução que
  falhou) e transforma um deles em regra com um clique.
- **Histórico** guarda o diário, o que foi enviado, e **Desempenho**: alarmes por hora,
  avalanches de alarmes, os maiores ofensores, os alarmes permanentes, contra as metas da
  ISA-18.2.

## 6. Dashboards, relatórios e tendências (View)

Abra o **View**. Os **Dashboards** são feitos de **painéis** (indicador, medidor, tendência,
gráfico de barras, tabela, dispersão, texto):

- *Plant overview* tem um **link público**: quem tem o link vê o dashboard sem entrar, somente
  leitura.
- *Control room* troca as suas três páginas a cada minuto, para uma tela de parede.
- *Loop detail* tem uma **variável**: escolha outra malha no alto e todos os painéis a seguem.

**Tendências** desenha quaisquer sinais em qualquer período e salva a vista. **Relatórios**
transforma um dashboard num documento com agendamento (*U-100 daily report*, *Control loops
weekly performance*) e o exporta como Word, HTML ou Markdown.

## 7. Modelos e simulações (Models)

Abra o **Models**. Um modelo é um **diagrama de blocos** (Modelica por baixo) que você desenha a
partir da biblioteca ou escreve como código.

1. **Modelos** lista os exemplos. Abra o tanque: arraste um bloco, ligue-o, mude um parâmetro.
2. **Simular** inicia uma **simulação**; **Simulações** lista todas as simulações e a fila. Uma
   das simulações da história é alimentada com a última hora de uma malha real e comparada com
   ela.
3. **Estudos** executam um modelo muitas vezes (**Novo estudo**). *Tank size* e *Heat exchanger
   area* variam um parâmetro numa grade; abra um e compare as curvas.
4. **Exportar FMU** empacota um modelo para que o Analytics possa executá-lo ao lado da planta,
   como faz o exemplo do forno.

O trabalho pesado roda em **workers de processamento**, longe dos apps: um administrador os vê
em Configurações › Processamento e pode adicionar máquinas
([Workers de processamento](../compute.md)).

## 8. Notebooks

Abra o **Notebooks** para usar Python com os dados da planta: JupyterLab no navegador, ou o
mesmo notebook no seu próprio computador com o kit do PlantCraft Notebooks. Os exemplos leem
sinais do Historian, resultados do Analytics e simulações do Models com poucas linhas, como a
pessoa que os executa ([Notebooks](notebooks.md)).

## 9. Perguntar ao assistente

Em qualquer página, o botão **Assistente** oferece primeiro as **tarefas** daquela página: *Por
que este alarme disparou?* num alarme, *Quais alarmes devemos corrigir primeiro?* em Desempenho,
*Explicar este dashboard* no View, *Ajudar a criar um novo bloco* no Analytics. Ele lê só o que
você pode ler, pela mesma API e com as mesmas permissões que você tem, e nunca escreve: uma
criação volta como uma proposta que você confirma.

O assistente precisa de um modelo de linguagem, e a suíte não vem com nenhum ligado. Até um
administrador configurar um em Configurações › Modelos de linguagem, o painel avisa isso, e o
especialista Valve em Mensagens responde com respostas roteirizadas. Veja
[o assistente](../assistant.md).

## 10. Do seu jeito

| Para | Vá para |
|---|---|
| Conectar a sua planta | Historian › Fontes, depois PlantCraft › Ativos ([Guia do usuário](user-guide.md)) |
| Carregar o mapa da planta de uma planilha | [Arquivo de configuração](configuration-file.md) |
| Adicionar pessoas, grupos e quem abre qual app | PlantCraft › Pessoas ([Guia do usuário](user-guide.md)) |
| Pôr o seu próprio algoritmo nas suas malhas | Analytics › Algoritmos › Novo, depois Monitores › Novo |
| Fazer backup, atualizar, conferir os certificados | [Operar a suíte](running-the-suite.md) |
| Construir um app seu | O [modelo de app](../../templates/app) |

As palavras usadas aqui são definidas uma vez no [glossário](../glossary.md); as ideias por trás
delas estão em [Conceitos](concepts.md).
