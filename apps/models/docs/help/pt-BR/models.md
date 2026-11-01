# Models

O Models desenha modelos de processo como **diagramas de blocos** e os simula ao longo do tempo,
como o Simulink: blocos com entradas e saídas são ligados entre si, você escolhe o início, o fim,
o solver e o passo dele, e **Simular** integra o diagrama. Por trás do diagrama está o Modelica, a
linguagem aberta para modelos de sistemas físicos, e o OpenModelica faz o cálculo.

O Models serve para estudo: o que um tanque maior ou outra sintonia fariam. Ele nunca roda na
planta; os algoritmos que rodam sobre os dados da planta são do Analytics.

## As palavras que o Models usa

| Palavra | O que é |
|---|---|
| **Bloco** | Uma peça com entradas, saídas e parâmetros: um degrau, um ganho, uma função de transferência, um PID, um tanque, um scope. Os blocos vêm em bibliotecas (**Blocos** no menu). |
| **Modelo** | Blocos ligados em um diagrama, com as configurações da simulação: uma malha de nível, um trocador de calor. |
| **Simulação** | Uma execução de um modelo: as configurações, os resultados e as mensagens dela. |
| **Estudo** | Um modelo simulado sobre uma grade de valores de parâmetros, para comparar as simulações e encontrar a melhor. |
| **Simulações** (página) | Tudo o que rodou: os estudos e as simulações avulsas de cada modelo, com a fila. |

## Por onde começar

1. **Modelos** lista os modelos. Três exemplos estão lá desde o início: **TankLevelControl**
   (um PID mantém o nível de um tanque pela bomba de carga), **HeatExchangerOutlet** e
   **FirstOrderDeadTimeLoop**.
2. Abra **TankLevelControl**. A página dele tem as abas que um algoritmo tem no Analytics:
   **Visão geral** (o que ele é), **Entradas e saídas** (o que ele lê, o que seus scopes mostram e
   os parâmetros de cada bloco: o padrão do bloco, a menos que o modelo defina seu próprio valor),
   **Diagrama** (o setpoint, o controlador, a bomba, o tanque, o transmissor de nível e dois
   scopes; **Abrir o editor** o abre em uma janela própria), **Testar**, **Usado por** (os estudos
   do modelo), **Versões** e **Configurações** (de quando a quando, com qual solver e passo, e onde
   o modelo é guardado). Salvar uma alteração gera uma nova versão e pergunta o que mudou.
3. Em **Testar**, clique em **Executar o teste**: uma simulação com as configurações do modelo, uma
   verificação. Os resultados plotam o que os scopes mostram: o nível seguindo o setpoint.
4. É um estudo que simula um modelo de verdade: em **Estudos**, clique em **Novo estudo**, escolha
   o modelo, defina `tank.A` como uma faixa de 2 a 6 em 5 valores e `tank.Cv` como a lista 0.03,
   0.05, 0.08: quinze simulações começam, e a página do estudo as classifica pelo indicador que você
   escolher e pode desenhá-las lado a lado, um gráfico por tamanho de tanque. Um valor que o estudo
   não define é o do modelo, e um que o modelo não define é o padrão do bloco.

Os exemplos ficam como vêm no Models. **Duplicar** faz uma cópia sua para alterar.

**Compilar**, na página de um modelo, gera o modelo como está agora e guarda a versão compilada
com ele: uma FMU (FMI 2.0, cossimulação), a forma que o Analytics executa. Ao lado do botão, a
página diz se o modelo está **Compilado** (e a partir de qual versão), **Desatualizado** (ele, ou
um bloco que ele usa, mudou depois da compilação), **A compilação falhou** ou **Não compilado**. A
**Versão compilada** da Visão geral diz quando e por quem, quanto tempo levou e o que o omc disse,
baixa a FMU e lista as três últimas compilações. O teste e os estudos continuam compilando no
executor enquanto rodam; um estudo reaproveita a compilação que seus lotes compartilham.

A página de um bloco tem as abas de um bloco no Analytics: **Visão geral** (como ele é desenhado,
o que faz, como ler e a fórmula), **Entradas e saídas** (as portas e os parâmetros), **Código**,
**Usado por** (os modelos que o colocam) e **Versões**. Os blocos que acompanham o Models ficam como
estão; **Duplicar** copia qualquer um deles para a biblioteca própria deste site, onde os valores
padrão mudam em Entradas e saídas e cada vez que salvar gera uma nova versão que diz o que mudou. Um
valor definido em um modelo prevalece sobre o padrão do bloco, e um definido por um estudo
prevalece sobre o do modelo.

Há um só tipo de modelo: um diagrama de blocos. Um modelo escrito em código Modelica (os fornos
com que o Analytics aprendeu, por exemplo) é um bloco do seu próprio diagrama: as entradas e saídas
reais dele são as portas do bloco, e os parâmetros dele, as configurações do bloco. As equações
ficam no código, a um clique (**Código Modelica**).

## Quem pode fazer o quê

| Papel | Pode |
|---|---|
| Leitor | Ler os modelos, blocos, estudos e simulações, com os gráficos e as mensagens |
| Editor | Todo o resto: desenhar e salvar modelos, simulá-los, iniciar e cancelar estudos, exportar FMUs, escrever bibliotecas de blocos |

## Onde as coisas ficam guardadas

Modelos, bibliotecas de blocos, simulações, seus resultados e FMUs são guardados pelo Models na
pasta de dados da suíte. Uma simulação guarda uma cópia do modelo como ele estava quando ela
começou, então os resultados sempre correspondem ao diagrama que os gerou. **Código**, na página
de um modelo, mostra o texto Modelica dele.
