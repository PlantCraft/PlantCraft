# Glossário pt-BR

> **Estado:** rascunho para revisão do mantenedor (2026-11-01). Toda tradução para o português
> segue esta tabela. Uma palavra, um sentido, em toda a suíte, como em [glossary.md](glossary.md).
> Mudar um termo aqui significa trocá-lo em todos os catálogos (`locales/pt-BR.json`).

## Regras

- **Os nomes dos produtos não são traduzidos:** PlantCraft, Analytics, Historian, View, Alarms,
  Models, Documents, Desk, Notebooks e Simulator.
- Ids, código, unidades, tags (`FIC-101.PV`), nomes de arquivos e termos de API também não.
- Use o português do Brasil, em registro técnico e direto, como em um manual de engenharia de
  processos. Os botões ficam no infinitivo ("Salvar", "Excluir"), sem "você" sempre que der.
- Use maiúscula só na primeira palavra ("Saúde do sistema", não "Saúde do Sistema").
- Os campos `{nome}` ficam iguais ao inglês. Pode mudar a ordem das palavras ao redor deles, mas
  nunca o campo.
- Os números e as datas são escritos pelo `locale`, nunca pelo texto traduzido.
- Os termos da ISA-18.2 seguem a tradução corrente no Brasil (reconhecer, suprimir, fora de
  serviço).

## Palavras da suíte

| Inglês | Português | Observação |
|---|---|---|
| Signal / Signals | Sinal / Sinais | nunca "ponto" ou "variável" |
| Tag | Tag | só o endereço do sinal na fonte |
| Label | Rótulo | palavra-chave livre |
| Derived signal | Sinal derivado | |
| Calculated signal | Sinal calculado | |
| Asset / Assets | Ativo / Ativos | |
| Asset type | Tipo de ativo | |
| Role | Papel | o papel de um sinal no ativo |
| Target / Targets | Alvo / Alvos | antes havia "Assuntos" no catálogo; padronizado como Alvo |
| Result / Results | Resultado / Resultados | |
| OK, Warning, Critical, Unknown | OK, Atenção, Crítico, Desconhecido | níveis de um resultado |
| Event / Events | Evento / Eventos | |
| Run / Runs | Execução / Execuções | |
| Simulation | Simulação | em Models |
| Queue | Fila | |
| Compute, Worker, Compute task | Processamento, Worker, Tarefa de processamento | "worker" fica em inglês |
| Folder | Pasta | |
| Group | Grupo | só de pessoas |
| Library | Biblioteca | de blocos |
| Overview | Visão geral | |
| Widget | Widget | |
| Panel | Painel | elemento de um dashboard ou relatório |
| Dashboard | Dashboard | já é o uso corrente na indústria |
| Report | Relatório | |
| Trend / Trends | Tendência / Tendências | |
| Settings | Configurações | da instalação e de cada app |
| Preferences | Preferências | de cada pessoa |
| People | Pessoas | |
| System health | Saúde do sistema | |
| Assistant | Assistente | |
| Specialist | Especialista | |
| Task (do assistente) | Tarefa | |
| Alarm / Alert | Alarme / Alerta | o alarme exige reconhecimento, o alerta não |
| Source / Sources | Fonte / Fontes | |
| Plant | Planta | |
| Unit | Unidade | |
| Workspace | Espaço de trabalho | |
| Inbox | Caixa de entrada | |
| Messages, Chats, Notifications | Mensagens, Conversas, Notificações | |
| Today, Actions, Calendar, To-do, Notes, Team | Hoje, Ações, Agenda, Tarefas, Notas, Equipe | páginas do Desk |
| Audit log | Registro de auditoria | |
| Backups, Updates | Backups, Atualizações | |
| App keys | Chaves dos apps | |
| Token | Token | |
| Public link | Link público | |
| Sign in / Sign out | Entrar / Sair | |
| Owner | Responsável | |
| Share | Compartilhar | |
| Help | Ajuda | |
| Search | Buscar | |

## Controle e malhas (Analytics)

| Inglês | Português | Observação |
|---|---|---|
| Loop / Loops | Malha / Malhas | malha de controle |
| Control loop | Malha de controle | |
| Controller | Controlador | |
| Setpoint (SP) | Setpoint (SP) | |
| Process variable (PV) | Variável de processo (PV) | as siglas ficam em inglês |
| Controller output (OP/MV) | Saída do controlador (OP/MV) | |
| Valve | Válvula | |
| Stiction | Agarramento (stiction) | |
| Oscillation | Oscilação | |
| Tuning | Sintonia | |
| Gain, Integral time, Derivative time | Ganho, Tempo integral, Tempo derivativo | |
| Manual / Automatic / Cascade | Manual / Automático / Cascata | modos da malha |
| Saturation | Saturação | |
| Performance index | Índice de desempenho | |
| Block / Blocks | Bloco / Blocos | |
| Algorithm | Algoritmo | |
| Monitor | Monitor | um algoritmo nos seus alvos, com cadência |
| Method | Método | |
| Finding | Achado | |
| Check | Verificação | |
| Cadence | Cadência | |
| Recorded outputs | Saídas gravadas | |

## Historian

| Inglês | Português |
|---|---|
| Scan | Varredura |
| Deviation (compression) | Desvio |
| Max interval | Intervalo máximo |
| Retention | Retenção |
| Step | Degrau |
| Archive | Arquivo |
| Backfill | Preenchimento retroativo |
| Import / Export | Importação / Exportação |
| Collector | Coletor |
| Compression | Compressão |
| Rollup | Agregação |

## Alarms (ISA-18.2)

| Inglês | Português |
|---|---|
| Acknowledge / Acknowledged | Reconhecer / Reconhecido |
| Unacknowledged | Não reconhecido |
| Shelve / Shelved | Suprimir / Suprimido |
| Out of service | Fora de serviço |
| Return to normal (RTN) | Retorno ao normal (RTN) |
| Priority: Critical, High, Medium, Low | Prioridade: Crítica, Alta, Média, Baixa |
| Rule / Rules | Regra / Regras |
| Silence / Silences | Silenciamento / Silenciamentos |
| Journal | Diário |
| Chattering alarm | Alarme repetitivo (chattering) |
| Standing alarm | Alarme permanente |
| Flood | Avalanche de alarmes |
| Deadband | Banda morta |
| Delay (on / off) | Atraso (na ativação / na desativação) |

## Models

| Inglês | Português |
|---|---|
| Model / Models | Modelo / Modelos |
| Study / Studies | Estudo / Estudos |
| Simulation settings | Configurações da simulação |
| Solver | Solver |
| Category | Categoria |
| Indicator | Indicador |
| Compile | Compilar |
| Parameter | Parâmetro |
| Input / Output | Entrada / Saída |
| Steady state | Regime permanente |
| Optimization | Otimização |

## Escolhidos durante a tradução (a revisar)

| Inglês | Português | Onde / observação |
|---|---|---|
| Target (meta de desempenho ou de atendimento) | Meta | metas de alarmes e de pedidos; "Alvo" fica para o alvo de um resultado |
| Editor / Viewer (papéis) | Engenharia / Leitura | |
| Operations (app) | Operação | |
| Request | Pedido | |
| Partners | Parceiros | |
| My day | Meu dia | |
| Handover | Passagem de turno | |
| Uptime | Disponibilidade | |
| Sign-ins | Logins | |
| Chats | Conversas | |
| Calendar | Agenda | |
| Schedule (do backup) | Programação | não colide com Agenda |
| Process display / diagram | Tela de processo | View |
| Stat, Gauge, Dial | Valor, Indicador, Mostrador | painéis do View |
| Threshold | Limiar | |
| Wire | Ligação | blocos |
| Gate | Barreira | |
| Tracking | Acompanhamento | Models |
| Parameter sweep | Varredura de parâmetros | colide com Scan = Varredura |
| Overshoot, Settling time | Sobressinal, Tempo de acomodação | |
| Step (de tempo, Models) | Passo | no Historian, "Step" é Degrau |
| Clear / Cleared (alarme) | Normalizar / Normalizado | |
| Raise (alarme) | Disparar | |
| Stale alarm | Alarme permanente | |
| Board (console) | Painel de operação | |
| DCS | SDCD | |
| Surge level | Nível pulmão | |
| Replay | Reexecução | |
| Critical (prioridade) | Crítica | uma mesma chave serve a nível e prioridade em alguns apps |
| Archive | Arquivo | colide com "arquivo" (file); alternativa: "Acervo" |
| Scope, Model exchange, claim | em inglês | |
