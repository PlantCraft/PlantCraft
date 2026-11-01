# Histórico de execuções

**Resultados > Histórico de execuções** lista todas as execuções de todos os algoritmos em uma só
lista, as mais recentes primeiro: execuções do algoritmo Qualidade dos sinais sobre os sinais,
rodadas de monitoramento e execuções de algoritmos que uma pessoa ou um monitor iniciou em malhas
escolhidas. Não há uma página separada para sinais e para malhas: os filtros **Algoritmo** e
**Status** restringem a lista, e cada coluna ordena.

Cada execução mostra quando começou, o algoritmo, em que rodou, seu estado, o que encontrou, quanto
tempo levou e o que a iniciou. Abra uma execução para ver seus resultados e perguntar ao
assistente sobre ela.

As execuções também são informadas ao PlantCraft, que as lista na sua página Resultados com as
execuções dos outros apps.

## Monitores

**Monitores** diz quando cada algoritmo roda. A página de um monitor tem quatro partes:

- **O que executa**: o algoritmo, os ativos ou malhas em que roda e quantos dados cada execução lê.
- **Quando**: uma vez, ou a cada N minutos, horas, dias, semanas ou meses. A cada N minutos ou horas
  pode rodar só em alguns dias da semana e só entre dois horários (a cada 15 minutos, de segunda a
  sexta, das 06:00 às 18:00); dias, semanas e meses rodam em um ou mais horários; meses rodam em
  um dia do mês (ou no último dia) ou em um dia da semana, como a primeira segunda-feira. Um
  primeiro e um último dia são opcionais. Os horários seguem o fuso horário escolhido, primeiro a
  hora local da instalação ou UTC, então 06:00 continua 06:00 nas mudanças de horário de verão.
- **Se falhar**: quando uma execução não consegue ler a planta ou não encontra dados, ela tenta de
  novo (duas vezes, com cinco minutos de intervalo, por padrão) e desiste quando a próxima
  ocorrência do monitor vem antes. Um erro no próprio algoritmo não é tentado de novo.
- **Responsável e prioridade**: quem responde por ele (o Alarms o avisa), seu lugar na fila, como
  suas execuções se distribuem e se está ativo.

A prévia à direita descreve o monitor em palavras e lista suas próximas cinco ocorrências. Um
monitor salvo mostra seu histórico acima: quantas execuções rodaram, falharam e foram tentadas de
novo, quanto tempo levaram e desde quando vale o último resultado.
