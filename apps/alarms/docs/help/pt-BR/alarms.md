# Alarms

O Alarms avisa a pessoa certa quando algo precisa de ação. As **regras** leem duas coisas e
decidem:

- **Valores**: os sinais da planta e o que os apps calculam e guardam como séries, como a saúde
  de uma malha no Analytics (um valor por execução).
- **Eventos**: o que os apps da suíte reportam, só quando algo muda: uma execução do Analytics
  que falhou, um sinal do Historian sem dados, um achado aberto.

Uma regra que vale dispara um **alarme**; nada vira alarme sozinho.

## Por onde começar

O menu segue a ordem em que as coisas acontecem: os eventos chegam, as regras os leem, os
alarmes são disparados.

1. **Visão geral** mostra os alarmes num relance, em widgets que cada pessoa organiza; passe o
   mouse sobre o título de um widget para ver o que ele mostra e em que ordem. O widget de
   desempenho abre **Desempenho**, que compara a carga de alarmes com os **Alvos** da ISA-18.2
   e da EEMUA 191.
2. **Eventos** lista o que os outros apps reportaram: **Abertos agora** (iniciados e não
   encerrados) ou **Todos** em um período, filtrados por tipo, app, ativo, severidade ou estado.
   Os eventos não notificam ninguém. Uma linha abre o evento: de onde veio (um link para a
   execução do Analytics por trás dele), o que o app enviou, os inícios e fins anteriores da
   mesma condição e as regras que o leem; **Criar uma regra a partir dele** começa uma regra ali.
3. **Regras** lista cada regra como uma frase, cada uma ligada ou desligada a partir da lista.
   **Nova regra** escreve uma no formulário Simples ou em Python. A aba **Silenciamentos** retém
   as mensagens durante uma parada programada.
4. **Alarmes** reúne todos os alarmes em uma tabela, os mais urgentes primeiro: **Precisa de
   atenção** (o padrão), **Não reconhecido** ou **Todos**, e **Só os meus**. Uma linha abre o
   alarme: seu valor, seu histórico (cada disparo, normalização, reconhecimento e alteração) e
   as mensagens enviadas sobre ele.

## Uma regra, muitos alarmes

Uma regra cobre ativos nomeados, todos os ativos sob um ramo, todos os ativos de um tipo, os
ativos de um monitor do Analytics, ou qualquer ativo que seus eventos citem, e gera **um alarme
por ativo** por padrão: "PV acima de 50 sob a Unidade 100" é uma regra e uma dúzia de alarmes.
Cada alarme tem sua própria vida ISA-18.2 (disparado, reconhecido, suprimido), enquanto as
mensagens da regra inteira são agrupadas, para que cinquenta malhas não virem cinquenta
mensagens. Veja **Regras** e **Notificações**.

## De onde vêm os dados

O Alarms lê os valores e os eventos da suíte só pelo PlantCraft, com a sua própria chave do
app, a cada poucos segundos. Ele nunca se conecta ao sistema de controle e nunca escreve nele:
ele informa, o operador age. Uma regra sobre ativos lê o valor de cada ativo (o seu papel `pv`,
ou a série de um app sobre ele), então quando o mapa da planta passa um papel para outro sinal,
o alarme acompanha.

Cada disparo e normalização também é enviado ao PlantCraft como um evento, e cada ativo mostra
seu estado de alarme nos outros apps (a menos que a saída **Dashboards** da regra esteja
desligada).
