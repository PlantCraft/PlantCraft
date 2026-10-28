# Stack

As bibliotecas sobre as quais a suíte é construída, por área: o que usamos, versão e licença, e
onde escrevemos algo nosso que uma biblioteca madura poderia fazer. Serve para acompanhar a
stack e decidir trocas quando valer a pena. As versões são as fixadas na versão 0.3.0
(`deploy/requirements.lock`, `package-lock.json`, os digests das imagens nos Dockerfiles); o
inventário de licenças para publicação está em `docs/publishing.md`.

Revisado em: 2026-10-23.

## Linguagens e execução

| O quê | Versão | Licença | Onde |
|---|---|---|---|
| Python | 3.13 (`python:3.13-slim-trixie`) | PSF | Servidor de cada app |
| TypeScript | 5.8 | Apache-2.0 | Todas as interfaces |
| Node.js | 22 (só no build) | MIT | Gera as interfaces; não vai nas imagens que rodam |

## Backend (servidores web e API)

| Biblioteca | Versão | Licença | Onde |
|---|---|---|---|
| FastAPI | 0.148 | MIT | API de cada app e a API v1 |
| Starlette | 1.9 | BSD-3 | Por baixo do FastAPI |
| Uvicorn | 0.54 | BSD-3 | O processo servidor |
| Pydantic | 2.14 | MIT | Modelos de requisição e de configuração |
| httpx | 0.28 | BSD-3 | Cliente da API v1 no SDK, testes |
| requests | 2.34 | Apache-2.0 | PI Web API (com `requests-kerberos`, ISC) |
| itsdangerous | 2.2 | BSD-3 | Cookie de sessão assinado |

## Dados e cálculo

| Biblioteca | Versão | Licença | Onde |
|---|---|---|---|
| NumPy | 2.5 | BSD-3 | Métodos e blocos, compressão, alarmes |
| pandas | 3.0 | BSD-3 | Séries no SDK, métodos do Analytics, exportações |
| openpyxl | 3.1 | MIT | Mapa da planta e arquivo de configuração em Excel |
| ReportLab | 5.0 | BSD-3 | Relatórios PDF do Analytics |
| graphlib (biblioteca padrão) | Python 3.13 | PSF | Ordem e verificações de um diagrama de blocos |
| FMPy | 0.3.32 | BSD-2 | Roda FMUs (modelos de processo) no Analytics |
| lxml | 6.1 | BSD-3 | Descrição das FMUs no Analytics |
| OpenModelica (`omc`) | 1.24.4 | OSMC-PL / GPL-3.0 | Contêiner runner do Models, programa separado |

## Bancos de dados

| O quê | Versão | Licença | Onde |
|---|---|---|---|
| SQLite (biblioteca padrão) | Python 3.13 | Domínio público | Banco próprio de cada app |
| PostgreSQL | 17.11 | PostgreSQL | Arquivo do Historian |
| psycopg + psycopg-pool | 3.3 | LGPL-3.0 | Conexão do Historian ao PostgreSQL |

## Conexões com a planta

| Biblioteca ou ferramenta | Versão | Licença | Onde |
|---|---|---|---|
| asyncua | 1.1.8 | LGPL-3.0 | Cliente OPC UA (Historian) e servidor (Simulator) |
| Telegraf | a distribuída pela InfluxData | MIT | Gateway do Historian: fontes MQTT, Modbus TCP e SQL |

## Interface

| Biblioteca | Versão | Licença | Onde |
|---|---|---|---|
| React | 19.2 | MIT | Todas as interfaces |
| Vite | 7.3 | MIT | Build e servidor de desenvolvimento |
| Plotly.js (`plotly.js-cartesian-dist-min`) + `react-plotly.js` | 3.7 / 4.1 | MIT | Todos os gráficos; o `@plantcraft/ui` dá o visual comum (`timeChart`) |
| React Flow (`@xyflow/react`) | 12.12 | MIT | Editor de diagramas de blocos (`BlockEditor`, Analytics) |
| CodeMirror | 6 | MIT | Editores de código Modelica e Python (Models) |
| FullCalendar (`@fullcalendar/*`) | 6.1 | MIT | Calendário da Desk: ano, mês, semana, dia e lista; eventos criados e movidos arrastando |
| Tiptap (`@tiptap/*`, sobre ProseMirror) | 3.31 | MIT | Notas da Desk: texto formatado, checklists e menções com `#` (só as extensões gratuitas) |
| Lucide (`lucide-react`) | 0.468 | ISC | Ícones |
| Inter e JetBrains Mono (no `@plantcraft/ui`) | Fontsource 5.3 | OFL-1.1 | Fontes, embutidas (sem serviço de fontes) |

## Login e segurança

| Biblioteca ou ferramenta | Versão | Licença | Onde |
|---|---|---|---|
| cryptography | 50.0 | Apache-2.0 / BSD | Chaves Ed25519, Fernet para senhas de fontes, assinatura dos pacotes |
| PyJWT | 2.15 | MIT | Tokens entre o PlantCraft e os apps (`plantcraft_sdk.jwt`) |
| argon2-cffi | 25.1 | MIT | Senhas (Argon2id; hashes PBKDF2 antigos são trocados no login) |
| joserfc | 1.7 | BSD-3 | ID tokens do OpenID Connect: assinatura e claims (`directory/jose.py`) |
| ldap3 | 2.9 | LGPL-3.0 | Login corporativo com LDAP ou Active Directory |

## Empacotamento e execução

| Ferramenta | Versão | Licença | Onde |
|---|---|---|---|
| Docker + Compose | 29 (CLI do instalador) | Apache-2.0 | Um contêiner por app, pacote offline |
| Caddy | 2.11 | Apache-2.0 | Proxy HTTPS da suíte |
| Debian (`trixie-slim`) | 13 | Várias (DFSG) | Base das imagens |

## Testes e qualidade

| Ferramenta | Versão | Licença | Onde |
|---|---|---|---|
| pytest | 8 | MIT | Todos os testes Python |
| Vitest + jsdom | 5 / 26 | MIT | Testes de interface |
| Playwright | 1.64 | Apache-2.0 | Jornadas no navegador (`make e2e`) |
| Ruff | 0.17.1 | MIT | Lint e formatação Python |
| ESLint | 9 | MIT | Lint das interfaces |

## Feito por nós, e o que poderia substituir

Partes que escrevemos embora exista biblioteca, com o veredito da revisão de 2026-10-23. As três
trocas que valiam já foram feitas: senhas em Argon2id, tokens em PyJWT e ID tokens do OpenID
Connect em joserfc (a biblioteca JOSE do Authlib). O resto é **mais tarde** (só quando acontecer
o gatilho da nota) ou **manter** (a biblioteca traria mais do que tira).

| Nosso | Onde | Alternativa | Veredito |
|---|---|---|---|
| Backup do Historian (`pg_dump`) | `processcraft/apps/operations.py` | pgBackRest (MIT) | **Mais tarde**: quando o arquivo passar de uns 100 GB (já planejado) |
| Partições do arquivo do Historian | `histcraft/archive/partitions.py` | pg_partman (PostgreSQL) | **Mais tarde**: se a manutenção das partições crescer; compressão e rollups ficam nossos |
| Tabela de dados (ordenar, buscar, filtros, páginas) | `ui/src/DataTable.tsx` | TanStack Table (MIT) | **Mais tarde**: quando uma lista ficar longa demais para o navegador; aí a solução é paginar no servidor, o que a biblioteca não faz |
| Traduções (`t()`, catálogos JSON) | `processcraft/i18n`, `ui/src/i18n.ts` | i18next ou FormatJS (MIT) | **Mais tarde**: quando a interface precisar de um terceiro idioma ou plurais por idioma |
| Stores SQLite e migrações para frente | `sdk/python/plantcraft_sdk/server/store.py` (~170 linhas) | SQLAlchemy Core + Alembic (MIT) | **Mais tarde**: se algum app precisar rodar em outro banco |
| Assinatura das versões (Ed25519) | `processcraft/apps/release.py`, `deploy/bundle.sh` | minisign (ISC), Sigstore cosign (Apache-2.0) | **Mais tarde**: cosign só quando as versões forem públicas; ele precisa de internet, o pacote não |
| Renderizador de Markdown | `ui/src/Markdown.tsx` | `react-markdown` + `remark-gfm` (MIT) | **Manter**: pequeno, não gera HTML cru e desenha nossos diagramas flow e stack |
| Tour do produto | `ui/src/Tour.tsx` | Driver.js (MIT) | **Manter**: cinco idiomas e a moldura da suíte já embutidos |
| Navegação entre páginas | `ui/src/nav.ts` (~60 linhas) | React Router (MIT) | **Manter**: cada app tem poucas páginas |
| Motor de blocos | `sdk/python/plantcraft_sdk/blocks` | pipefunc, PathSim (MIT) | **Manter**: decidido em 2026-10-22, as bibliotecas eram novas demais |
| Agendamentos, fila de jobs e workers | `linkcraft/engine` | APScheduler, Procrastinate (MIT) | **Manter**: seriam duas bibliotecas (e PostgreSQL para o Procrastinate) para fazer o que o SQLite do app já faz |
| Compressão, chunks e rollups do Historian | `histcraft/archive` | TimescaleDB | **Manter**: swinging door é o método dos historiadores de planta, e a compressão do TimescaleDB é Timescale License, não código aberto |
| Cliente de modelo de linguagem | `processcraft/specialists/model.py` | SDKs oficiais, LiteLLM (MIT) | **Manter**: HTTP puro fala os dois formatos sem dependência; desligado por padrão |
| SBOM da imagem | `sdk/python/plantcraft_sdk/sbom.py` | Syft (Apache-2.0) | **Manter**: o Syft já é usado quando instalado; o nosso é o plano B offline |
| Cliente PI Web API | `histcraft/sources/pi_web_api.py` | Nenhuma madura e aberta | **Manter** |
| Motor de alarmes (indicadores ISA-18.2) | `alarmcraft/engine` | Nenhuma madura e aberta | **Manter** |
| Métodos de malhas de controle | `linkcraft/methods` | Nenhuma madura e aberta em Python | **Manter**; só métodos públicos |
