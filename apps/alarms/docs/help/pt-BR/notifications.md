# Notificações

O Alarms avisa as pessoas sobre os alarmes nas **Mensagens** do PlantCraft e, quando o PlantCraft
tem seu e-mail configurado (Configurações › E-mail) e a pessoa permite isso no seu perfil, por
**e-mail**. Cada regra diz quem fica sabendo dos seus alarmes, na parte **Mensagens** das suas
**Saídas**. O e-mail aparece ali assim que o PlantCraft consegue enviá-lo.

## Quem

- **O responsável**: para um alarme sobre eventos, o responsável que o app indica nos seus
  eventos (no Analytics, o responsável pelo monitor); senão, o responsável pela regra. É o padrão.
- Pessoas e grupos do PlantCraft (como "Operação U-100").
- Desligado: os alarmes da regra só aparecem no Alarms.

## Quanto, e quando

| Parte | Significado |
|---|---|
| Agrupar por | Todo alarme da regra disparado dentro deste tempo (5 minutos por padrão) sai em **uma** mensagem: "Malha crítica 3 vezes em 1 h: 12 malhas na Unidade 100" |
| Lembrar a cada | Enquanto um alarme continua ativo e não reconhecido, ele é enviado de novo; reconhecer interrompe. 0 nunca lembra |
| Também quando normaliza | Uma mensagem também quando o alarme volta ao normal |
| Horários | Sempre, **só dentro** de certos horários (um turno diurno), ou **só fora** deles (sobreaviso), no fuso horário da regra. Quando os horários começam com um alarme ainda esperando, ele é repassado uma vez |
| Se ninguém reconhecer | Passos de escalonamento: após tantos minutos, avisar mais pessoas, como **o coordenador** dos grupos notificados (definido no PlantCraft, Pessoas › Grupos) |

## O que chega às pessoas: a filosofia de alarmes

Visão geral › Desempenho › **Alvos** guarda as metas da instalação. O Alarms as mede
(**Desempenho**, com os dez alarmes mais frequentes) e as usa para manter poucas mensagens. Os
padrões são as metas públicas da ISA-18.2 e da EEMUA 191; um editor as altera, e cada alteração
fica na auditoria do PlantCraft.

| Proteção | O que faz |
|---|---|
| Por prioridade | **Crítica** vai na hora, um a um, sem agrupamento nem limite. **Alta** vai conforme sua regra a agrupa. **Média**, **baixa** e todo alerta esperam o **resumo do turno** (07:00 e 19:00 por padrão, no fuso horário da filosofia): uma mensagem por pessoa com o que esperou. Uma regra ainda pode pedir **Sempre na hora** nas suas saídas |
| Agrupamento | Uma mensagem por regra e janela de agrupamento, não uma por alarme |
| Um limite por pessoa | Ninguém recebe mais de 6 mensagens por hora do Alarms. Acima disso, um aviso diz que há mais esperando no Alarms. Os alarmes críticos e os escalonamentos sempre saem |
| Avalanche | Mais de 10 alarmes para uma pessoa ou um grupo em 10 minutos: recebem **uma** mensagem de avalanche ("Avalanche de alarmes: 23 alarmes em 10 min") em vez de cada um, a cada 10 minutos enquanto durar; os alarmes críticos continuam chegando um a um. O Alarms escreve o evento `alarmcraft.flood.started` |
| Repetitivo (chattering) | Um alarme disparado 3 vezes em um minuto, ou 10 em uma hora, para de enviar; o resumo o lista com o que mudar (uma banda morta, um atraso na ativação) |
| Permanente | Um alarme ativo há mais de 24 horas não é mais lembrado; o resumo o lista para revisão |
| Inibição | Enquanto o alarme "falhou" ou "travado" de um monitor do Analytics estiver ativo, os outros alarmes desse monitor não são anunciados. Enquanto a vigilância da suíte reportar o Historian ou seu coletor fora do ar (ou o instalador mudo, ou o Docker fora do ar), os alarmes de "sem dados" e as execuções que falharam também não são anunciados: essa é a causa deles, já informada aos administradores. O mesmo vale enquanto o Historian reportar seu coletor travado; enquanto reportar uma fonte desconectada, só os alarmes de "sem dados" dos sinais dessa fonte esperam |

## Nas Mensagens

Cada ocorrência de um alarme é uma conversa nas Mensagens: o disparo, os lembretes, os
escalonamentos e a normalização chegam na mesma conversa, que volta a ficar não lida a cada um. A
mensagem tem os botões **Reconhecer** e **Abrir a regra** ao lado de Abrir, e o filtro "Alarms"
as encontra. **Reconhecer** reconhece o alarme na hora, em seu nome, sem abrir o Alarms (um
acesso somente leitura é recusado). Os alarmes críticos e de prioridade alta também aparecem em
destaque em qualquer app que você tiver aberto, com os mesmos botões. Um alerta não precisa de
reconhecimento: sua mensagem tem só **Abrir a regra**. As mensagens que agrupam vários alarmes
abrem o Alarms, filtrado pela regra deles.

Quando o alarme é reconhecido (aqui, no Alarms ou por outra pessoa), normalizado ou colocado fora
de serviço, sua conversa fica **resolvida para todos** que a receberam: sai da contagem de não
lidas, perde os botões e diz o que a resolveu ("Reconhecido por ana", "Normalizado"). Uma
mensagem que agrupa vários alarmes é resolvida quando todos eles forem. Um novo disparo do alarme
é uma nova conversa.

## Silenciamentos

Um **silenciamento** (Regras › Silenciamentos) retém as mensagens de alguns alarmes (áreas,
disciplinas ou alarmes escolhidos) por um tempo, com um motivo: uma parada programada, uma
parada geral. Os alarmes continuam sendo disparados, exibidos e registrados. Para parar o
próprio alarme enquanto o instrumento é consertado, **suprima-o** (Operação dos alarmes).

## O que foi enviado

A página de cada alarme lista suas **Mensagens enviadas**: quando, para quem, e se foi enviada.
Quando o PlantCraft não consegue receber uma mensagem (porque está reiniciando, por exemplo), ela
espera e é tentada de novo a cada ciclo por um dia.

O projeto segue descrições públicas de ferramentas de alertas (as regras e o agrupamento de
notificações do Grafana Alerting; o agrupamento, a inibição e os silenciamentos do Prometheus
Alertmanager) e a linha que a ISA-18.2 traça entre suprimir um alarme (shelving) e não avisar
sobre ele.
