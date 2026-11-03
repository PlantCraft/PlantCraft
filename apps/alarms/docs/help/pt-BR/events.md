# Eventos

**Eventos** é o que os outros apps da suíte reportaram ao PlantCraft. Os apps reportam só
mudanças: uma execução do Analytics que falhou (um evento por execução, não um por ativo), um
sinal do Historian que parou de enviar e quando volta, um achado aberto ou fechado. O PlantCraft
descarta um início que já está aberto e um fim de algo que não existe, e limita cada app a 1000
eventos por hora, para que um app com defeito não inunde a suíte. O Alarms os lê a cada ciclo e
os guarda por 30 dias.

Os eventos nunca notificam ninguém. Uma regra decide quando um evento vira um alarme.

## Abertos agora e Todos

**Abertos agora** (o padrão) lista as condições iniciadas e ainda não encerradas. Um app reporta
uma condição como dois eventos, seu **início** e seu **fim**, com uma **chave** que a identifica
(um serviço, um sinal, o achado de uma malha). Uma regra "aberta por pelo menos 10 min" dispara
com uma condição dessas e normaliza sozinha com o fim dela.

**Todos** lista cada evento do período (24 horas, 7 ou 30 dias), os mais novos primeiro. Filtre
por tipo, app, ativo, severidade, estado (aberto, encerrado, instantâneo) ou se uma regra o
contou; **Regras** cita as regras que contaram cada evento.

## Começar uma regra a partir de um evento

**Criar uma regra** em um evento abre uma nova regra preenchida a partir dele: o tipo do evento,
o ativo de que trata, aberto por pelo menos tanto tempo ou contado tantas vezes. Escolha as
saídas, depois **Teste** a regra nos últimos dias.

Quando o Alarms inicia pela primeira vez, mostra aqui os eventos do último dia, sem contá-los:
as regras avaliam o que acontece dali em diante.

No Analytics, o **Criar regra de alarme** de um monitor abre uma nova regra já preenchida para
ele: cada ativo em que ele roda encontrado crítico, um alarme por ativo, normalizado quando o
status volta a ok.
