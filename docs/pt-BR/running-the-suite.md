# Operar a suíte

O que um administrador acompanha depois que a suíte está instalada: o fuso horário, a saúde, os
backups, as atualizações e o app Operação. Toda página citada aqui fica no PlantCraft, em
**Administração**, ou no Operação.

## Fuso horário

A suíte guarda e calcula todo horário em UTC. As telas os mostram em **Hora local**: o fuso
horário da instalação, o mesmo para todos.

- **Configurações › Instalação** define esse fuso, escolhido numa lista. O `install.sh` o inicia
  com o fuso do próprio servidor. Mude-o quando o servidor usa outro horário (um servidor em UTC
  numa planta no Brasil, por exemplo). Os horários guardados nunca mudam, só a forma como são
  mostrados e quando rodam os agendamentos salvos em hora local.
- Onde um formulário pede um fuso horário (o agendamento do backup, um monitor do Analytics, as
  horas em que um alarme pode notificar, uma importação de CSV), ele oferece primeiro **Hora
  local**, depois **UTC**, depois deslocamentos fixos (UTC−1 … UTC−12, UTC+1 … UTC+14) e, por
  último, as cidades, para fusos com horário de verão. Um agendamento salvo em **Hora local**
  acompanha a instalação se o fuso dela mudar depois.
- Cada pessoa escolhe em **Preferências** (o menu dela, embaixo da barra lateral) se vê a Hora
  local, UTC ou, quando está em outro lugar, o horário do próprio dispositivo. Essa escolha fica
  salva na conta dela e é a primeira que os formulários dela oferecem.

## Saúde do sistema

**Saúde do sistema** mostra cada serviço da suíte com o estado, a CPU, a memória e os
reinícios. A suíte se verifica a cada 30 segundos; quando uma parte para, cada administrador
recebe uma mensagem em **Mensagens** (de "Sistema") e um aviso no alto das páginas do
PlantCraft, e outra quando ela volta. **Baixar pacote de diagnóstico** salva o que o suporte
precisa: versões, o estado de cada serviço e o fim do log dele, e as configurações sem nenhum
segredo. Nunca bancos de dados, dados da planta ou chaves.

### Certificados

**Saúde do sistema › Certificados** lista os certificados que a suíte usa, com a data em que
cada um vence: o de HTTPS e os das conexões OPC UA do Historian. Cada administrador recebe uma
mensagem 30 dias antes de um vencer e outra 7 dias antes. **Renovar** cria um novo certificado
para o cliente OPC UA do Historian; baixe-o e faça cada servidor OPC UA confiar nele, ou a
conexão para. O certificado de um servidor é renovado no servidor e depois aceito de novo na
fonte dele; o certificado de HTTPS é trocado na pasta `certs/` da instalação.

## Backups

A suíte faz o próprio backup enquanto roda, todo dia no horário de **Programação** (02:00 Hora local
por padrão), e confere cada backup antes de contá-lo. Ela guarda 7 backups diários, 4 semanais
e 3 mensais, e o feito antes da última atualização.

- **Fazer backup agora** faz um na hora. **Conferir de novo** (o escudo na lista) confere um de
  novo.
- Uma vez por semana (domingo às 03:00 por padrão) o **teste de restauração** restaura o último
  backup bom numa cópia separada da suíte, sem rede e sem porta, a inicia, a confere e a
  remove. A suíte em execução não é tocada. **Testar uma restauração agora** o executa na hora.
- **Restaurar** põe cada banco de dados, configuração e imagem de volta como estavam naquele
  backup. Digite o nome do backup e a sua senha para confirmar. A suíte para por alguns minutos;
  o que estava lá é posto de lado, não excluído, e a suíte volta a ele sozinha se a restauração
  não subir saudável.

No servidor, `sudo ./install.sh --backup`, `--list-backups` e `--restore NAME` fazem o mesmo.

## Atualizações

Uma atualização vem como um pacote assinado. No servidor, a partir da pasta do novo pacote:

```bash
sudo ./install.sh
```

Ele confere a assinatura, faz backup, atualiza e confere a nova versão. Quando a nova versão não
está saudável, ele volta sozinho para a anterior. **Atualizações** mostra a versão instalada, as
notas da versão dela e cada atualização com o resultado.

## Operação

**Operação** fica ao lado do Desk no seletor de apps, para administradores e para pessoas com o
papel **Operação** (a TI, ou a equipe de um integrador, sem torná-las administradoras).

- **Status**: a CPU e a memória de cada app contra o próprio limite ("86 %, 3,4 de 4 CPUs"), a
  CPU, a memória, a carga e o disco livre da máquina, e os incidentes. A **disponibilidade** de
  cada app em 24 horas, 7 e 30 dias deixa de fora a manutenção planejada. Um administrador
  planeja uma **janela de manutenção** (agora ou depois, todos os apps ou alguns, até 72 horas);
  enquanto ela dura, a vigilância fica em silêncio sobre esses apps.
- **A máquina e o perfil dela**: a saúde da suíte indica a máquina como o Docker a vê, o
  **perfil de máquina** que dimensionou a suíte (small, medium, large ou xlarge) e o limite de
  CPU de cada serviço ao lado do uso. Quando a máquina se encaixa em outro perfil (mais memória
  adicionada, um perfil fixado à mão), ela o indica com o comando para aplicá-lo no servidor,
  `sudo ./install.sh --machine auto`. Nada é mudado pela web.
- **Logs**: o log de cada servidor numa só lista, com filtros de período, nível, texto,
  requisição e app, os avisos e erros mais frequentes, "Mesmo pedido em todos os apps" e
  exportação para CSV.
- **Alertas de carga**: avisa os administradores quando um app ou a máquina fica acima de um
  nível (CPU ou memória em 80 % para atenção e 95 % para crítico, ou erros registrados por
  minuto) por 5 minutos. Os níveis são mudados na página.
- **Pedidos**: qualquer pessoa pede ajuda com **Pedir ajuda** no menu dela, em todos os apps,
  com o app e a página já preenchidos; um registro de log e um incidente aberto têm **Abrir um
  pedido**. Cada fila pode ter um horário de trabalho, e cada prioridade uma meta de primeira
  resposta e uma de resolução; os relógios correm só no horário de trabalho e param enquanto um
  pedido está Bloqueado. Pedidos mostra o tempo que falta ou o atraso. O tempo é lançado em
  qualquer pedido ou ação, faturável ou não.
- **Parceiros**: as empresas que trabalham na planta (grupos do tipo **Empresa**), cada uma com
  o coordenador, as equipes, um patrocinador na planta e um último dia de acesso, depois do qual
  ninguém dela entra. Parceiros mostra as pessoas, os acessos, os pedidos abertos e as horas do
  mês de cada empresa. Depois que um mês termina, um administrador ou o patrocinador aprova as
  horas, e o mês é fechado. Um patrocinador sem o papel Operação vê só Pedidos e Parceiros, das
  próprias empresas.
- **Acesso temporário de suporte**: um administrador dá a uma pessoa o Operação por até 72
  horas, com um motivo. Ele termina sozinho ou com **Encerrar agora**, a pessoa é avisada, e os
  dois ficam no registro de auditoria.

## No servidor

Estes rodam no servidor, a partir da pasta da instalação, como root:

- `./install.sh --security-check`: 36 verificações da instalação, com uma pontuação;
  `--format json`, `junit`, `sarif` ou um relatório de evidências para uma auditoria. Exceções
  podem ser registradas com data de fim.
- `./install.sh --rotate-admin-password`: uma nova senha para o administrador de emergência,
  mostrada uma vez. A verificação de segurança falha quando essa senha tem mais de 90 dias.
- `./install.sh --machine small|medium|large|xlarge|auto`: dimensiona todos os contêineres a
  partir de uma escolha.
- `./install.sh --show-config`: o arquivo da instalação (`/etc/plantcraft/installation.conf`) e
  se ele está aplicado. Os valores dele prevalecem sobre a linha de comando e o `.env`.

O pacote também traz um modelo do Zabbix (`monitoring/plantcraft_zabbix_agent.yaml`, Zabbix 7.0
ou mais novo) que vigia a máquina, o disco livre e cada serviço com os mesmos níveis dos alertas
de carga.
