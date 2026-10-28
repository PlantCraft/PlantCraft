# PlantCraft: guia de segurança para TI e automação

Duas páginas entregues às equipes de TI e de automação do cliente a cada versão. Descreve a
instalação da suíte com Docker ([install-offline.md](../install-offline.md)). Itens marcados como
**planejado** estão em `docs/gaps.md` e ainda não valem; **parcial** diz o que falta. A versão em
inglês, [`docs/security-guide.md`](../security-guide.md), é a de referência; esta tradução a
acompanha a cada versão.

## 1. O que é e o que não faz

O PlantCraft lê dados de processo de um historiador (PI Web API), de servidores OPC UA ou de
arquivos CSV e entrega análises (PlantCraft Analytics, Historian, View, Alarms e Models;
repositórios `linkcraft`, `histcraft`, `dashcraft`, `alarmcraft`, `modelcraft`) aos navegadores.
**Nunca escreve** em SDCD, CLP, PI ou servidor OPC UA: os conectores de dados (do PlantCraft e do
Historian) não têm chamada de escrita. A planta de demonstração (PlantCraft Simulator, perfil `demo`)
é uma imagem separada que o PlantCraft e o Historian apenas leem. Nada é enviado para a internet:
sem telemetria, verificação de atualização, chamada de licença, fonte web ou CDN
(`tests/test_offline.py`).

**Modelos de linguagem vêm desligados.** O PlantCraft pode deixar seus especialistas responderem
com um modelo de linguagem que o administrador configura em Configuração › Modelos de linguagem
([collaboration.md](../collaboration.md)): um modelo na rede da empresa (vLLM, Ollama, um gateway) ou
uma API na nuvem. Até lá nada é enviado a modelo nenhum. `PLANTCRAFT_LLM=off` proíbe modelos na
instalação, seja o que for que as configurações digam. O modelo é alcançado pelo conduíte da planta
Z4, então o `firewall.sh` precisa listar o `host:porta` dele, como para um servidor PI. **Assistentes
de IA** chegam à suíte pelo caminho inverso, pelo servidor MCP somente leitura (seção 4), também
desligado por padrão.

## 2. Onde instalar (modelo de Purdue)

Num servidor Linux no **nível 3** (operações do site, ao lado do historiador) ou na **DMZ industrial
(nível 3.5)**. Nunca nos níveis 0 a 2. Os usuários chegam a ele a partir dos níveis 3 ou 4 por
HTTPS; ele lê do nível 3 (PI) ou de servidores OPC UA que a equipe de automação expõe ao nível 3. Não
precisa de nenhuma conexão de entrada vinda dos níveis 0 a 2 e não abre nenhuma para o nível 4 ou a
internet.

## 3. Zonas e conduítes (IEC 62443-3-2)

```text
 Usuários nível 4/3 ──C1 HTTPS 443──▶ [edge: proxy] ──▶ [apps: PlantCraft, Link,
                                                         View, Historian, Alarms, Models]
                                                         │ (rede interna, sem rota para fora)
                                      [histdb: só o Historian e o histcraft-db] (interna)
                                      [plant: PlantCraft, Historian] ──C2──▶ PI Web API 443, OPC UA 4840
                                      [demo: PlantCraft, Historian e Plant, o simulador]
                                                         (rede interna, sem rota para fora)
```

| Zona ou conduíte | O que tem | Controles |
|---|---|---|
| Z1 Servidor | O servidor e o Docker | Endurecimento e atualizações do cliente; só Docker e SSH são necessários |
| Z2 Borda | Proxy (Caddy) | A única porta publicada (443); TLS com o certificado do cliente ou uma CA local; sem API de administração; sem NAT de saída, então não consegue sair |
| Z3 Apps | PlantCraft (uid 10001), View (10006), Historian (10008), Alarms (10009), Models (10011), Analytics (10012) | Rede Docker com `internal: true`: nenhuma rota para fora do servidor; os apps só chegam aos dados da planta pela API do PlantCraft, com tokens assinados, exceto o Historian (linha abaixo) |
| Banco do Historian | `histcraft-db`, o PostgreSQL do Historian (uid 10008) | Rede interna própria `histdb`, compartilhada só com o Historian: nenhum outro contêiner (proxy, PlantCraft, Analytics, View) abre conexão com ele; sem porta publicada; scram-sha-256 com uma senha que só o Historian tem |
| Coleta do Historian | Historian (perfil `histcraft`) | O historiador e a camada de dados da suíte: lê as próprias fontes (OPC UA, PI Web API, arquivos CSV em `data/histcraft-csv`, só leitura), criadas na página Fontes, por isso é o segundo componente no conduíte da planta Z4, sob as mesmas regras do `firewall.sh`; também entra na rede interna `demo` para ler o Plant. Senhas das fontes são cifradas com `data/histcraft/secret.key` |
| Workers de cálculo | `compute-gateway` (uid 10020, imagem do PlantCraft) e os executores dos apps `linkcraft-executor` e `modelcraft-executor` (uid 10020), aqui e em outras máquinas (docs/compute.md) | Rodam o código que as pessoas escrevem: análises e código de blocos do Analytics, jobs Modelica do Models. Os executores não têm rede nenhuma (`network_mode: none`), nenhum segredo, raiz só leitura, `/tmp` em tmpfs noexec, sem capabilities, `no-new-privileges`, limites de CPU, memória e processos e limite de tempo e memória por tarefa; a única ligação é a sua pasta em `data/compute-jobs/` (modo 0700), compartilhada com o gateway. O gateway guarda a credencial do worker, não abre porta e pede tarefas ao PlantCraft pela rede interna `compute` (outra máquina: por HTTPS); um administrador pausa ou revoga um worker em Settings › Compute. O executor do Models (imagem `modelcraft-runner`) é a única imagem com compilador C (o OpenModelica precisa); o Models e o executor recusam código `external` e funções de arquivo ou de sistema antes de rodar um job |
| Instalador | Serviço `installer` (uid 10005) | O único contêiner com o socket do Docker; nenhuma rede (`network_mode: none`), só leitura, sem capabilities; só age sobre pacotes assinados que ele mesmo verifica |
| Z4 Conduíte da planta | PlantCraft e Historian | Saída para os servidores PI e OPC UA que o administrador cadastra; o `firewall.sh` limita toda a rede da planta a esses pares `host:porta` |
| Demo | Plant (só com `--demo`), PlantCraft e Historian | Rede Docker com `internal: true`: o simulador não tem rota para fora do servidor |
| DNS | Todos os contêineres | Nenhuma consulta de nome de fora da suíte sai do servidor: o proxy e o Plant só resolvem nomes de serviço, o PlantCraft também, a não ser que `PLANTCRAFT_DNS` aponte o DNS da planta, e os apps ficam em redes internas |
| C1 Usuários → Z2 | HTTPS | HSTS, cookies de sessão seguros, login obrigatório, 10 tentativas erradas bloqueiam por 5 minutos |
| C2 Z4 → PI/OPC UA | HTTPS / OPC UA binário | Conta de serviço só de leitura no PI; OPC UA anônimo ou usuário e senha (**planejado:** assinatura e criptografia OPC UA) |

O `tests/test_isolation.py` prova no CI que só o proxy publica porta, que um contêiner de app não tem
rota para fora (uma conexão para a internet falha) nem alcança a rede da planta ou o banco do
Historian, que nenhum contêiner resolve nome externo e que todo contêiner roda como descrito na
seção 5.

## 4. Contas e acesso

- O login é obrigatório nesta instalação; a senha do administrador de emergência é gerada na
  instalação (24 caracteres aleatórios, arquivo com modo 0600, nunca vai para log).
- Perfis admin, editor, leitura e só dashboards, com acesso por aplicação, aplicados pela API. Os
  apps recebem tokens de vida curta assinados com Ed25519 (15 minutos) e os verificam offline
  (`docs/api-v1.md`). O `tests/test_route_permissions.py` percorre todas as rotas e falha se alguma
  responder sem sessão ou acima do nível de quem chama. **Parcial:** fora desta instalação Docker o
  login ainda é opcional.
- Links de calendário do Desk (desligados por padrão, `docs/desk.md`): quando um admin liga e
  indica os servidores permitidos, o PlantCraft lê esses endereços `.ics` por https a cada 15
  minutos (no máximo 2 MB, sem credenciais no link, endereços da rede interna recusados).
  Importar um arquivo `.ics` não usa a rede.
- Login corporativo (desligado por padrão, `docs/corporate-login.md`): Active Directory ou LDAP só
  por LDAPS ou StartTLS, e login único com OpenID Connect (PKCE, state, nonce, ID tokens
  assinados). Os grupos do diretório viram níveis, apps e grupos; a conta admin da instalação
  sempre entra localmente. **Ainda não:** SAML.
- Trilha de auditoria central: quem mudou o quê (pessoas, grupos, ativos, apps, chaves,
  configurações, backups), no PlantCraft e em cada app (os apps gravam a sua por
  `POST /api/v1/audit`), com o nome da pessoa, guardada no banco do PlantCraft, e cada login, tentativa
  falha, login bloqueado e saída, com o endereço de origem e o método (local, LDAP, OIDC). Os
  administradores leem em Settings › Registro de auditoria (filtros, busca, CSV); as linhas só são
  acrescentadas.
- Acesso de assistentes de IA (desligado por padrão, `docs/assistant-access.md`): um servidor MCP
  somente leitura em `/mcp`, pelo qual o assistente de IA da própria pessoa lê a planta, com um
  token de acesso dessa pessoa (mostrado uma vez, guardado como SHA-256, com validade, revogável) e
  exatamente o acesso dela. Nada escreve; toda chamada de ferramenta vai para a auditoria;
  `PLANTCRAFT_MCP=off` proíbe na instalação.
- Notebooks (desligados por padrão, `docs/pt-BR/notebooks.md`): o JupyterLite vem na imagem,
  então o Python roda no navegador de cada pessoa, nunca no servidor, e lê a API v1 como essa
  pessoa. Nada é baixado durante o uso (sem recorrer ao PyPI). Só as páginas em
  `/notebooks/lite/` recebem uma Content-Security-Policy que também permite `'unsafe-eval'
  'wasm-unsafe-eval'` (WebAssembly e o código que o JupyterLab gera); todas as outras mantêm
  `script-src 'self'`. No computador da pessoa o mesmo pacote lê com o token de acesso dela, só
  leitura, enquanto os Notebooks estão ligados. `PLANTCRAFT_NOTEBOOKS=off` os proíbe na
  instalação.
- Demo pública (`install.sh --public-demo`, desligada por padrão): os visitantes entram como
  visitas de uma conta de leitura (poucos lugares ao mesmo tempo, alguns minutos cada; de fora a
  conta nunca entra com senha); toda escrita de um visitante responde 403 (ele só pode sair e
  marcar mensagens como lidas), modelos de linguagem ficam desligados para ele, e cada visita é
  limitada a `PLANTCRAFT_PUBLIC_DEMO_RATE` requisições por minuto (429) e a poucas requisições
  simultâneas em cada app. Nunca ligue numa instalação com dados reais de planta.
- Senhas de fontes digitadas na interface ficam cifradas em repouso, com uma chave guardada na
  pasta de dados.

## 5. Contêineres e dados

- Todo contêiner: usuário sem root, sistema de arquivos raiz só leitura, todas as capabilities do
  Linux removidas, `no-new-privileges`, limites de CPU, memória e processos, health checks,
  política de reinício. As imagens não têm compilador nem gerenciador de pacotes (o pip é removido),
  exceto o compilador do executor Modelica (linha acima); as dependências Python vêm de wheels
  conferidos por hash.
- Todo o estado fica numa pasta (`data/`, uma subpasta por usuário de contêiner: `processcraft/`,
  `linkcraft/`, `dashcraft/`, `alarmcraft/`, `modelcraft/`, `compute-jobs/`, `histcraft/`,
  `histcraft-db/`, `proxy/`, `simcraft/`). Chaves de app (`data/<app>-app-key`) e a senha do banco do Historian
  (`data/histcraft-db-password`) são arquivos com modo 0600 do usuário do app, passados como
  secrets do Docker. Nenhum dado sai do servidor. Backup é copiar a pasta da instalação; há backups
  online agendados (o banco do Historian por blocos, cheio e incremental, com as ferramentas do
  próprio PostgreSQL, [operations.md](../operations.md)) e um ensaio de restauração, toda
  atualização faz um backup antes e `./install.sh --rollback` volta à versão anterior.
  **Planejado:** `processcraft rollback` para instalações sem Docker (G12). O PlantCraft não
  cifra os dados em repouso: use a criptografia de disco do servidor se for exigida.

## 6. Instalar, atualizar e remover

Pacote offline por versão: imagens `.tar`, arquivo compose, instalador, SBOM, somas SHA-256. Não
precisa de internet para instalar, atualizar ou voltar versão. Remoção: `./install.sh --uninstall`
mantém os dados; `--purge` apaga. **Versões assinadas:** o publicador assina o `SHA256SUMS` (o hash
de todos os arquivos, imagens incluídas) com uma chave Ed25519; o hash do pacote é conferido com
`ssh-keygen` antes de desempacotar, e o `install.sh` confere a assinatura de novo antes de instalar
e a cada atualização, contra a pasta `trusted-publishers/` da instalação
([install-offline.md](../install-offline.md), seção 2). Pacotes para x86_64 e arm64. **Planejado:**
instalador Windows sem administrador, wheelhouse para instalações sem Docker (G11).

**Apps.** Administradores adicionam apps pela página Apps (um arquivo `.pcapp` assinado, o catálogo
online ou o endereço de um app externo) ou com `./install.sh --add <arquivo>`
([app-package.md](../app-package.md)). Todo pacote é conferido contra as chaves de publicador em
`trusted-publishers/` (assinatura Ed25519 do manifesto, SHA-256 da imagem e do SBOM); publicador,
permissões e SBOM aparecem antes de confirmar, e cada passo vai para a auditoria. Um pacote nunca
pode pedir para escrever na planta (`plant_write`) ou alcançar hosts de fora (`outbound`), nem
definir o próprio ambiente, volumes ou portas. O catálogo online fica desligado até
`PLANTCRAFT_APP_CATALOG_URL` ser definido e um administrador ligá-lo; plantas isoladas o deixam
desligado.

Acesso ao socket do Docker equivale a root no servidor. Ele fica restrito ao serviço `installer`: o
PlantCraft e os apps nunca o recebem, e o PlantCraft só deixa pedidos numa pasta que o
instalador lê. O instalador não tem rede, confere de novo cada pacote com a própria cópia, só
leitura, das chaves confiáveis e roda cada app com o mesmo endurecimento da suíte. **Para desligar
as instalações de apps**, defina `PLANTCRAFT_APP_INSTALL=off` no `.env` e não rode o serviço
`installer` (tire-o do `compose.yaml` ou `docker compose stop installer`); a página Apps passa a
só listar apps e cadastrar apps externos.

## 7. Integridade das versões e cadeia de suprimentos

Somas SHA-256 de cada arquivo e do pacote; imagens base fixadas por digest; dependências Python
fixadas com hashes; SBOMs CycloneDX das dependências Python e da interface web, mais o SBOM que a
imagem de um app traz (`sbom/<app>.json`, hoje o View); o PostgreSQL vem como a imagem
oficial fixada por digest. O CI roda pip-audit e npm audit em cada mudança (falha em qualquer
vulnerabilidade conhecida nos pacotes Python entregues e nas altas ou críticas dos pacotes npm
entregues). **Parcial:** o SBOM ainda não lista os pacotes de sistema operacional das imagens nem o
binário do Caddy (G13).

## 8. Requisitos de componente da IEC 62443-4-2 (meta SL1; SL2 onde indicado)

| Requisito | Situação |
|---|---|
| CR 1.1 Identificação e autenticação de usuários humanos | Atende: contas locais, Active Directory ou LDAP, login único com OpenID Connect |
| CR 1.2 Identificação de processos de software | Atende: chaves de app e tokens de serviço assinados (API v1) |
| CR 1.5 / 1.7 Gestão de autenticadores, força de senha | Atende: senhas com hash, no mínimo 8 caracteres, senha de admin gerada |
| CR 1.11 Tentativas de login sem sucesso | Atende: 10 falhas bloqueiam por 5 minutos |
| CR 2.1 Aplicação de autorização | Atende na API, com teste de permissão de todas as rotas |
| CR 2.8 Eventos auditáveis | Sim: trilha central das mudanças no PlantCraft e nos apps, das chamadas de assistentes de IA e de cada login e saída, lida em Settings › Registro de auditoria |
| CR 3.1 / 4.1 Integridade e confidencialidade da comunicação | Atende em C1 (TLS); C2 depende do TLS dos servidores PI e OPC UA |
| CR 3.4 Integridade de software e de informação | Atende: somas SHA-256, imagens fixadas; versões e pacotes de app assinados (Ed25519) e conferidos antes de instalar e atualizar |
| CR 5.1 Segmentação de rede | Atende: zonas Z2 a Z4 acima (SL2) |
| CR 7.1 Proteção contra negação de serviço | Parcial: limites de recursos, limitação de tentativas de login |
| CR 7.3 / 7.4 Backup e recuperação | Atende: backups online agendados (o banco do Historian cheio e incremental), ensaio de restauração, backup antes de atualizar, rollback |
| CR 7.7 Funcionalidade mínima | Atende: sem root, só leitura, sem capabilities, sem API de administração, sem ferramentas de build (SL2) |
| Depende do cliente | Endurecimento do servidor, atualizações, segurança física, criptografia de disco, log central |

## 9. Contato

Para reportar vulnerabilidades, veja `SECURITY.md`.
