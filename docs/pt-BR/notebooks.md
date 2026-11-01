# Notebooks

**Notebooks** (no menu do Desk, depois de Agenda) é o Jupyter dentro do PlantCraft: Python com
numpy, pandas, scipy e matplotlib, e os dados da planta a uma chamada de distância. Ele roda no
seu navegador, no seu próprio computador (JupyterLite sobre Pyodide, embutido no PlantCraft: nada
é baixado da internet), e lê a planta pela API v1 com **o seu próprio acesso**: um notebook nunca
vê mais do que você pode ver.

## Rodar no navegador

Desk › Notebooks tem dois jeitos de rodar Python: **no navegador** e **no seu computador**.

- **Instalar o Python neste navegador** (uma vez, cerca de 130 MB, com o progresso): a página
  baixa Python, numpy, pandas, scipy, matplotlib e JupyterLab para este navegador. Na rede da
  planta leva segundos (cerca de 15 s medidos); depois a página confere se continuam lá e
  oferece **Abrir o JupyterLab** na hora. Uma versão nova do PlantCraft pede para instalar de novo.
- **Abrir o JupyterLab** abre uma aba nova com duas pastas: **Examples** (notebooks prontos que
  acham os próprios sinais e ativos, então rodam em qualquer instalação; uma pasta por app:
  `PlantCraft` para os dados da planta, `Link` para rodar os blocos e algoritmos do Analytics, e
  uma para cada outro app que traz exemplos) e **My notebooks** (o que o PlantCraft escreveu para
  você). Enquanto o Python inicia, a página avisa "Iniciando o Python no seu computador…" (cerca
  de 10 s depois de instalado).
- No Historian (um ponto, uma exportação): **Abrir num notebook**. O PlantCraft escreve um
  notebook cujas primeiras células já carregam esses sinais nesse período, e o abre numa aba nova.
- De qualquer página, `/notebooks?signals=<id>,<id>&start=<hora>&end=<hora>` faz o mesmo, e
  `/notebooks?asset=<id>` abre um ativo com os seus sinais.

Limites do navegador: a memória que uma aba pode usar (cerca de 2 a 4 GB), só os pacotes que vêm
junto (sem `pip install` de outros), mais lento que o Python no seu computador em contas pesadas,
e o que você muda (um exemplo também) fica só neste navegador: **File › Download** salva o
notebook como `.ipynb`, e o botão de enviar arquivo o traz de volta. "Neste navegador", no canto
superior direito do JupyterLab, indica isso. Para mais, rode no seu computador.

## Lendo a planta

```python
import plantcraft_notebook as pc

pc.me()  # com que pessoa o notebook lê
pc.signals("FIC")  # sinais cujo id, nome ou descrição contém FIC
data = pc.series(["plant:FIC-101.PV", "plant:FIC-101.SP"], "-7d", "now", step=60)
data.plot(subplots=True)  # uma coluna por sinal, índice de tempo em UTC
pc.value("plant:FIC-101.PV", agg="mean", window="24h")
pc.assets(type="loop")  # a árvore da planta
pc.asset("FIC-101")["signals"]  # os sinais de um ativo por papel
pc.results(subject="asset:FIC-101")  # o que os apps publicaram (saúde da malha, qualidade...)
pc.events(ref="asset:FIC-101")  # achados, alarmes que abriram e fecharam
```

Todo horário é UTC: um horário sem fuso é tomado como UTC, e `"now"`, `"-24h"` ou `"-7d"` contam
a partir de agora. `step` (segundos) dá uma média por passo; sem ele, os valores como gravados.
Períodos longos e muitos sinais são lidos em partes.

## Os objetos dos apps

Todo app se lê do mesmo jeito num notebook: `pc.app(...)` com o nome do app, e os objetos por
tipo. O que cada app oferece está em `pc.apps()`.

```python
link = pc.app("link")
link.kinds()  # block, algorithm
link.blocks()  # uma tabela: o mesmo que link.list("block")
spikes = link.get("block", "dq.spikes")  # um objeto inteiro: as portas e os parâmetros dele
run = spikes.run(asset="FIC-101", start="-24h")  # no PV da malha, aqui
run.values()  # cada saída: um veredito, um número, uma série
link.get("block", "transform.moving_average").run(x=my_series, window_samples=30)
link.get("algorithm", "flow").run(asset="FIC-101")  # um algoritmo inteiro numa malha
link.runtime().test_block(block_file, x=my_series)  # um bloco seu, testado como o Link testa
```

Os modelos do Models rodam no Models (OpenModelica), não no notebook: `.run()` coloca uma
simulação na fila dele, como faz o botão Simular, e `.wait()` lê a execução de novo até ela
terminar. Um administrador permite isso em Configurações › Apps › Models (**Simulações a partir
de notebooks**, desligado por padrão), e só os editores do Models podem. As regras e os alarmes
do Alarms são só leitura: um alarme vem com as ocorrências dos últimos 30 dias, que é por onde
começa um estudo de desempenho de alarmes. Os dashboards e relatórios do View também são só
leitura, cada um com os painéis ou seções e os sinais que mostram
(`pc.app("view").list("dashboard")`); o assistente os lista do mesmo jeito. Os exemplos de cada
app mostram o resto: `Examples/Analytics`, `Examples/Models`, `Examples/Historian`,
`Examples/Alarms`.

```python
models = pc.app("models")
models.models()  # todos os modelos, os exemplos primeiro
model = models.get("model", models.models().index[0])
run = model.run(stop=600).wait()  # na fila do Models, quando permitido
run["results"]  # cada variável: o tempo e os valores (reduzidos a 2000 pontos)
```

Um bloco ou um algoritmo roda **no notebook**, no seu computador ou neste navegador, com o código
que o Analytics executa: o primeiro `.run` traz o runtime do Analytics (o código Python dele,
menos de 1 MB, guardado por versão). Os dados são lidos com o seu acesso, como `pc.series` os lê.
Nada roda no servidor e nada é gravado lá: para manter um bloco, salve o arquivo dele e importe-o
no Analytics. Os blocos de um modelo (uma FMU) rodam só no Analytics.

## Rodar no seu computador

Para mais memória, pacotes seus, arquivos grandes ou cálculos longos, rode os mesmos notebooks no
JupyterLab do seu próprio computador com o **PlantCraft Notebooks**, um app para Windows (x64),
macOS (Apple silicon) e Linux (x64) que Notebooks › Rodar no seu computador oferece enquanto os
Notebooks estão ligados e a instalação o tem. Sem direitos de administrador, nada da internet,
nenhum comando.

1. **Instale uma vez.** O botão indica o seu sistema: um instalador para Windows (só para você,
   com uma entrada no menu Iniciar e um desinstalador em Configurações › Aplicativos), um app
   para macOS (arraste-o para Aplicativos), uma pasta com `Install.sh` para Linux. Ele traz
   Python 3.12, JupyterLab, numpy, pandas, scipy e matplotlib (as versões do navegador),
   `plantcraft-notebook` e os exemplos. Há também um zip portátil, que não precisa de instalação
   nenhuma.
2. **Conecte uma vez.** Notebooks › Rodar no seu computador › **Criar um código de conexão** dá
   uma linha (mostrada uma vez só): o endereço deste PlantCraft, um token seu (só leitura, como
   você, por 90 dias) e a impressão digital da autoridade certificadora da instalação. Abra o
   PlantCraft Notebooks (menu Iniciar, Aplicativos, o menu do Linux) e cole a linha quando ele
   pedir; no zip portátil, dê dois cliques em Configure token. O app confere a autoridade
   certificadora pela impressão digital e guarda o token no cofre do sistema (Gerenciador de
   Credenciais do Windows, Keychain do macOS, Secret Service no Linux; sem cofre, num arquivo que
   só você lê). O app avisa quando o token vence em menos de uma semana: crie um novo código
   então.
3. **Abra os notebooks.** Abra o PlantCraft Notebooks: o JupyterLab abre no seu navegador, com
   `Examples` e `My notebooks`. Uma faixa no topo do JupyterLab diz que ele roda no seu
   computador e lê qual PlantCraft, como quem. "Abrir num notebook" (Historian, View, um ativo)
   abre no navegador; abra o app para ter no seu computador os notebooks que o PlantCraft
   escreveu para você.

O JupyterLab escuta só em `127.0.0.1`, com uma senha que o app cria a cada início, e continua
rodando em segundo plano (o app o reaproveita; o menu Iniciar ou o app o abrem de novo). Os
notebooks ficam em `PlantCraft notebooks` nos seus Documentos, fora do app, então uma versão nova
os mantém; o navegador não os vê, nem o contrário. Cada abertura atualiza `Examples` e copia para
`My notebooks` os notebooks que o PlantCraft escreveu para você, nunca por cima de um que você
editou; num notebook, `pc.sync()` faz o mesmo. `%pip install <nome>` adiciona qualquer pacote,
quando o seu computador alcança um índice de pacotes.

Na primeira vez, o Windows pode dizer "O Windows protegeu o computador" (escolha Mais
informações, depois Executar assim mesmo) e o macOS que não consegue verificar o app (Ajustes do
Sistema › Privacidade e Segurança › Abrir Mesmo Assim): o app ainda não é assinado. Um link só
indica um servidor e um notebook: o app só se conecta depois que você confirma, só abre notebooks
de servidores já conectados e não executa nada que tenha vindo com o link.

**Sem o kit** (ou num Python seu: "Usar o meu próprio Python"): **baixe** ali o wheel do
`plantcraft-notebook` e mantenha o nome dele (o pip recusa um arquivo que o navegador renomeou,
como `...-2.whl`), instale-o num ambiente próprio (o macOS e a maioria dos Linux recusam um
`pip install` fora de um, PEP 668), **crie um token de acesso** e conecte:

```sh
python3 -m venv ~/plantcraft-env            # Windows: py -m venv plantcraft-env
source ~/plantcraft-env/bin/activate         # Windows: plantcraft-env\Scripts\activate
pip install jupyterlab matplotlib ~/Downloads/plantcraft_notebook-<version>-py3-none-any.whl
jupyter lab
```

```python
import plantcraft_notebook as pc

pc.connect("https://<servidor>", token="pcat_...")  # ou PLANTCRAFT_URL e PLANTCRAFT_TOKEN
```

Se o seu computador não confia no certificado do servidor, passe `ca="company-ca.pem"`. As outras
células do notebook rodam sem mudança; a linha `%pip install` da primeira célula é para o
navegador.

## Para administradores

- **Desligado por padrão.** Um administrador liga os Notebooks (PlantCraft › Configurações ›
  Notebooks), e toda mudança vai para o registro de auditoria (`notebooks.settings`, e
  `notebooks.create` para cada notebook que o PlantCraft escreve). `PLANTCRAFT_NOTEBOOKS=off` nas
  configurações da instalação os deixa desligados de vez.
- **O que roda onde.** O código Python roda no navegador de cada pessoa, não no servidor: o
  servidor só entrega os arquivos e responde a API v1 como essa pessoa. Um notebook pesado deixa
  lento o computador dessa pessoa, nunca o servidor da planta.
- **Limites por pessoa.** O que um notebook pede ao servidor (séries, sinais, eventos) tem limite
  por pessoa em Configurações › Notebooks: 120 requisições por minuto e 2 leituras ao mesmo
  tempo, por padrão. Contam todas as requisições à API v1 feitas com um token de acesso (um
  notebook ou script num computador, um limite por token) e as leituras de séries que o
  navegador da pessoa envia pelo proxy. Passado um limite, só essa pessoa recebe `429` com
  `Retry-After`, e o `plantcraft-notebook` espera e pede de novo sozinho (até 4 vezes, no máximo
  30 s cada). As leituras dos próprios apps (Analytics, Alarms, View), dentro da rede interna,
  nunca contam, então um notebook pesado nunca os deixa lentos. A primeira recusa de cada minuto,
  por pessoa, vai para o registro de auditoria (`usage.limited`).
- **O que um notebook pode fazer.** Exatamente o que a pessoa pode fazer no PlantCraft pela API
  v1, pela própria sessão: ler sinais, séries, ativos, resultados e eventos. Ligue os Notebooks
  quando as pessoas forem de confiança para rodar o código que escrevem ou recebem, como qualquer
  ferramenta de análise no computador delas.
- **Segurança.** As páginas dos notebooks (`/notebooks/lite/`) precisam que o navegador rode
  WebAssembly e código que o JupyterLab gera, então a Content-Security-Policy do proxy, só para
  essas páginas, também permite `'unsafe-eval' 'wasm-unsafe-eval'`. Elas continuam sem carregar
  nada de fora do servidor. Tokens de acesso leem a API v1 só enquanto os Notebooks estão
  ligados, e só leem (`GET`, e a leitura de séries `POST /api/v1/series`).
- A imagem leva o JupyterLite e um Pyodide enxuto (cerca de 130 MB), montados por
  `notebooks/build.py` com versões e SHA-256 fixados em `notebooks/pins.json`.
- **O kit** é uma parte opcional do pacote offline (`notebook-kits/`, cerca de 450 MB para os três
  sistemas), montado por `make notebook-kits` (o `make bundle` também os monta; no Mac mini, cada
  deploy que os muda) (`notebooks/kit/build_kit.py`: python-build-standalone e cada wheel fixados
  por SHA-256 em `notebooks/kit/pins.json` e `requirements.txt`). Ele é oferecido sempre que os
  Notebooks estão ligados e a instalação o tem; um administrador pode retirá-lo em Configurações
  › Notebooks › Kit para os computadores das pessoas. O PlantCraft acrescenta a cada zip, ao
  enviá-lo, o endereço do servidor e, com a autoridade certificadora local, o certificado raiz
  dela; nunca um token. Cada download vai para o registro de auditoria
  (`notebooks.kit_download`), e cada token de kit também (`assistant_token.create`). Um kit roda
  no computador da pessoa e só lê pela API v1, dentro dos limites acima.
