# Arquivo de configuração

O **arquivo de configuração** (o mapa da planta) monta uma instalação de uma
vez: as fontes de dados, os sinais em uso, a árvore de ativos e as malhas, num
único arquivo Excel ou JSON. Use-o para começar uma planta ou para copiar uma
instalação para outra. O dia a dia de fontes e sinais (navegar pelas tags,
escolher o que guardar, o histórico) fica no app **Historian**; só a árvore de
ativos se move com **Ativos › Importar** e **Exportar**.

> Desde 2026-10-24 o arquivo de configuração não tem página no PlantCraft (o
> responsável o achou pouco claro ao lado da importação de ativos, e enviar um
> arquivo sobre uma planta em uso era arriscado). Ele continua para instalações
> por script e para copiar uma instalação para outra, pela API com a sessão de
> um administrador: `GET /api/map/template.xlsx` ou `/api/map/export.json`,
> depois `POST /api/map/preview?filename=<file>` e
> `POST /api/map/apply?filename=<file>` com o arquivo no corpo
> (`ci/bench/suite_bench.py` faz exatamente isso). Na interface, a árvore de
> ativos é importada em **Ativos › Importar**, e a última importação pode ser
> desfeita lá; fontes e sinais são do Historian.

## O arquivo

O arquivo tem quatro listas: baixe o modelo, ou exporte a configuração atual,
preencha, confira a prévia e aplique.

- **Excel (.xlsx)**: uma aba por lista, com os nomes das colunas na primeira
  linha. A aba de leia-me do modelo explica cada coluna. Abas com nomes em
  português (`fontes`, `ativos`, `sinais`, `malhas`) também são aceitas.
- **JSON**: um objeto com as listas `sources`, `assets`, `signals` e `loops`.
- **CSV**: uma lista só, com o nome da aba como nome do arquivo
  (`signals.csv`, `assets.csv`...).

### `sources`

| Coluna | Obrigatória | O que é |
| --- | --- | --- |
| `source_id` | sim | Identificador usado na aba `signals`. `scenario` é a fonte do cenário (somente leitura). |
| `name` | sim | Nome mostrado na plataforma. |
| `type` | sim | `opcua`, `pi_web_api` ou `csv`. |
| `endpoint_url`, `namespace_uri` | OPC UA | Endereço do servidor e namespace dos NodeIds. |
| `base_url`, `server` | PI | Endereço do PI Web API e nome do PI Data Archive. |
| `path` | CSV | Caminho do arquivo no servidor. |
| `auth_type` | | OPC UA: `anonymous` ou `basic`. PI: `kerberos`, `ntlm` ou `basic`. |
| `username`, `password_env` | | Usuário e a variável de ambiente com a senha. Nunca escreva a senha no arquivo. |
| `timeout_seconds` | | Tempo máximo de cada leitura. |
| `tags` | PI | Tags da fonte separadas por `;`. |

### `assets`

| Coluna | Obrigatória | O que é |
| --- | --- | --- |
| `asset_id` | sim | Identificador sem espaços (`U-200`, `B-201A`). |
| `name` | sim | Nome mostrado na árvore. |
| `kind` | sim | Tipo do ativo: `unit`, `area`, `equipment`, `loop` ou outro tipo cadastrado na plataforma. |
| `parent_id` | | Ativo pai; vazio: direto sob a instalação. |
| `description` | | Descrição livre. |
| `attributes` | | Atributos do ativo: no JSON, um objeto (`{"power_kw": 75}`); na planilha, cada coluna extra da aba. Ainda não são guardados: a prévia avisa quais foram ignorados. |

### `signals`

| Coluna | Obrigatória | O que é |
| --- | --- | --- |
| `tag` | sim | A tag na fonte (NodeId de texto no OPC UA, ponto no PI, coluna no CSV). |
| `source_id` | | A fonte da tag; vazio: a fonte do cenário. |
| `name`, `unit` | | Nome legível e unidade de engenharia. |
| `asset_id` | | Ativo ao qual o sinal pertence. Uma tag pode aparecer em várias linhas, uma por ativo. |
| `role` | | O papel do sinal no ativo (`pv`, `pressure`, `vibration`...). |
| `monitor` | | `yes`/`no`: a plataforma acompanha o sinal. Vazio: sim. |

### `loops` (malhas de controle)

| Coluna | Obrigatória | O que é |
| --- | --- | --- |
| `loop_id` | sim | Tag da malha (`FIC-2001`); também é o id do ativo da malha. |
| `name` | sim | Nome da malha. |
| `asset_id` | | Ativo onde a malha fica na árvore (o equipamento). Vazio: sob a unidade e a área. |
| `area`, `unit`, `service` | | Área (agrupa nos painéis), unidade de processo e descrição curta. |
| `pv` | sim | Tag da variável de processo. |
| `sp`, `op`, `mode`, `secondary` | | Tags do setpoint, da saída, do modo e de uma variável secundária. |
Cada malha vira um ativo do tipo `loop` com os seus sinais por papel, e assim
todo app da suíte a encontra: o Analytics a analisa na próxima rodada. Como uma
malha é analisada (`protocol`, `loop_type`, `criticality`, `enabled`) é
definido no Analytics; essas colunas, quando presentes, são ignoradas aqui com
um aviso. Uma malha que vem do arquivo de cenário é alterada nesse arquivo, não
pelo mapa.

### Prévia, aplicar e reimportar

A prévia conta, por aba, o que será criado, alterado ou fica igual, e lista os
problemas com a aba e a linha (na planilha, a linha 2 é a primeira depois do
cabeçalho):

- **Erros** impedem a importação: coluna obrigatória vazia, tipo de ativo ou
  de fonte inválido, fonte ou ativo que não existe, malha sem `pv`, a mesma tag
  com duas fontes.
- **Avisos** não impedem: tag que não existe na fonte, ativo pai
  desconhecido (o ativo fica sob a instalação), senha que falta digitar,
  atributos e configurações de malha ignorados.

**Aplicar** (só administradores) grava tudo de uma vez. Importar o mesmo
arquivo de novo não muda nada. O que não está no arquivo fica como está; só
com a opção **Remover o que não está no arquivo** a plataforma remove as fontes
adicionadas, os ativos feitos à mão, os vínculos de sinais e as malhas de um
mapa que o arquivo não lista (as malhas do cenário nunca são removidas).

Para editar no Excel: **Exportar mapa atual (Excel)**, edite e importe de
volta. Sem edições, a prévia diz que nada muda.

## Montar o mapa a partir dos manuais com um modelo de linguagem

O caminho mais curto para uma planta nova costuma ser: juntar os manuais e as
listas de I/O dos equipamentos, pedir ao seu assistente de IA que monte o JSON
e conferir o resultado na prévia antes de aplicar. Para a árvore de ativos,
**Ativos › Importar › Copiar como prompt** põe um prompt pronto na área de
transferência: o formato do arquivo, um exemplo, os tipos de ativo desta
instalação e as regras que a resposta deve seguir. Para um mapa inteiro, o
mesmo tipo de prompt vem da API (`/api/prompts/plant-map`).

O botão só preenche a área de transferência: nada é enviado a lugar nenhum. O
prompt nunca leva o endereço, o usuário ou a senha de uma fonte de dados; as
fontes são configuradas em Configurações, e ao assistente só se pedem ativos,
sinais, malhas e relações.

Depois, confira a prévia do JSON (Ativos › Importar, ou `/api/map/preview`) e
leia-a com atenção: avisos de tags que não existem na fonte costumam ser erros
de leitura do modelo.

## Para quem implanta

- Fontes adicionadas ficam na tabela `data_sources` do banco; os sinais em uso
  e a fonte de cada tag, em `signal_routes`. A chave que cifra as senhas fica
  em `sources.key` ao lado do banco (ou no arquivo indicado por
  `PLANTCRAFT_SOURCES_KEY_FILE`). Sem a chave, as senhas guardadas precisam
  ser digitadas de novo.
- Cada leitura de dados vai para a fonte dona de cada tag; tags sem dona são
  lidas da fonte do cenário, exatamente como antes. Fontes OPC UA e PI
  adicionadas usam o mesmo cache local de histórico que a fonte do cenário.
- Ler e gravar planilhas Excel usa o pacote `openpyxl` (grupo `server` das
  dependências).
