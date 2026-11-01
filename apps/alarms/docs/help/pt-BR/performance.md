# Desempenho dos alarmes

A página Desempenho mede a carga de alarmes em um período (24 horas, 7 ou 30 dias) para uma
posição de operador, contra as metas públicas da ISA-18.2 e da EEMUA 191. Os alarmes suprimidos
e fora de serviço não disparam nada e não são contados.

| Indicador | Aceitável | Administrável |
|---|---|---|
| Alarmes por hora | até 6 | até 12 |
| Alarmes a cada 10 minutos | até 1 | até 2 |
| Tempo em avalanche (períodos de 10 minutos com mais de 10 alarmes) | abaixo de 1 % | abaixo de 5 % |
| Pico de alarmes em 10 minutos | até 10 | até 20 |
| Carga dos 10 alarmes mais frequentes | até 5 % | até 10 % |
| Alarmes repetitivos (chattering) (3 disparos em um minuto) | nenhum | |
| Alarmes permanentes (ativos há mais de 24 horas) | menos de 5 | menos de 10 |

A distribuição de prioridades é comparada com cerca de 5 % alta (crítica e alta), 15 % média e
80 % baixa.

## O nível EEMUA 191, as avalanches e o que o diário diz

- **Nível EEMUA 191**: o período como um ponto, média contra pico de alarmes a cada 10 minutos,
  nas quatro faixas da EEMUA 191: robusto, estável, reativo e sobrecarregado.
- **Avalanches**: uma avalanche começa acima do limite de avalanche (10 alarmes em 10 minutos) e
  termina abaixo da metade dele, para que uma pausa curta não a divida. Cada avalanche é listada
  com sua duração, seus alarmes e seu pico.
- **Horas acima de 30 alarmes**: a parcela das horas do período com mais de 30 alarmes.
- **Alarmes passageiros**: alarmes que voltam ao normal em até 10 segundos sem que ninguém aja.
  São candidatos a um atraso.
- **Tempo até o reconhecimento** por prioridade, como mediana e percentil 90.
- **Alarmes mais frequentes**: os 20 que disparam com mais frequência.

## Consoles (posições de operador)

As metas são para um operador. Quando a planta tem vários painéis de operação, defina os
**consoles** em Alvos › Consoles. Cada console lista:

- as **áreas** que atende, em qualquer nível da árvore de ativos (uma unidade, uma seção, um
  equipamento);
- quem fica nele;
- sua própria meta de alarmes por hora, se for diferente da carga por pessoa.

Um alarme vai para o console que cita a mais específica das suas áreas. Se dois consoles citam a
mesma área, ele vai para o primeiro. Um alarme que nenhum console cobre é contado em **Nenhum
console**.

O Desempenho então mostra uma tabela **Consoles** com a carga de cada console contra a sua
própria meta: alarmes por hora, o pico em 10 minutos e o nível EEMUA 191. O seletor **Console**
mostra todos os indicadores de um console. Quem fica em um console vê o próprio console primeiro.

## O que fazer com isso

Comece pelos **alarmes mais frequentes**: um punhado de alarmes problemáticos costuma fazer a
maior parte da carga. Para cada um, confira o limite, adicione uma banda morta ou um atraso, ou
pergunte se ele precisa mesmo ser um alarme. Os alarmes repetitivos quase sempre precisam de uma
banda morta. Os alarmes permanentes são um problema real que persiste ou um alarme que deveria
estar fora de serviço.
