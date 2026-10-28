# Notebooks

**Notebooks** (no menu, em Trabalho) é o Jupyter dentro do PlantCraft: Python com numpy, pandas,
scipy e matplotlib, e os dados da planta a uma chamada de distância. Ele roda no seu navegador,
no seu próprio computador (JupyterLite sobre Pyodide, embutido no PlantCraft: nada é baixado da
internet), e lê a planta pela API v1 com **o seu próprio acesso**: um notebook nunca vê mais do
que você pode ver.

## Rodar no navegador

Desk › Notebooks tem dois jeitos de rodar Python: **no navegador** e **no seu computador**.

- **Instalar o Python neste navegador** (uma vez, cerca de 130 MB, com o progresso): a página
  baixa Python, numpy, pandas, scipy, matplotlib e JupyterLab para este navegador. Na rede da
  planta leva segundos (cerca de 15 s medidos); depois a página confere se continuam lá e
  oferece **Abrir JupyterLab** na hora. Uma versão nova do PlantCraft pede para instalar de novo.
- **Abrir JupyterLab** abre uma aba nova com duas pastas: **Examples** (notebooks prontos que
  acham os próprios sinais e ativos, então rodam em qualquer instalação; uma pasta por app:
  `PlantCraft` para os dados da planta, `Link` para rodar os blocos e algoritmos do Analytics) e **My notebooks** (o que
  o PlantCraft escreveu para você). Enquanto o Python inicia, a página avisa "Starting Python on
  your computer…" (cerca de 10 s depois de instalado).
- No Historian (um ponto, uma exportação): **Abrir num notebook**. O PlantCraft escreve um
  notebook cujas primeiras células já carregam esses sinais nesse período, e o abre.
- De qualquer página, `/notebooks?signals=<id>,<id>&start=<hora>&end=<hora>` faz o mesmo, e
  `/notebooks?asset=<id>` abre um ativo com os seus sinais.

Limites do navegador: a memória que uma aba pode usar (cerca de 2 a 4 GB), só os pacotes que vêm
junto (sem `pip install` de outros), mais lento que o Python no computador em contas pesadas, e o
que você muda (um exemplo também) fica só neste navegador: **File › Download** salva o notebook
como `.ipynb`, e o botão de enviar arquivo o traz de volta. Para mais, rode no seu computador.

## Lendo a planta

```python
import plantcraft_notebook as pc

pc.me()  # com que pessoa o notebook lê
pc.signals("FIC")  # sinais cujo id, nome ou descrição contém FIC
dados = pc.series(["plant:FIC-101.PV", "plant:FIC-101.SP"], "-7d", "now", step=60)
dados.plot(subplots=True)  # uma coluna por sinal, índice de tempo em UTC
pc.value("plant:FIC-101.PV", agg="mean", window="24h")
pc.assets(type="loop")  # a árvore da planta
pc.asset("FIC-101")["signals"]  # os sinais de um ativo por papel
pc.results(subject="asset:FIC-101")  # o que os apps publicaram (saúde da malha, qualidade...)
pc.events(ref="asset:FIC-101")  # achados, alarmes que abriram e fecharam
```

Toda hora é UTC: uma hora sem fuso é tomada como UTC, e `"now"`, `"-24h"` ou `"-7d"` contam a
partir de agora. `step` (segundos) dá uma média por passo; sem ele, os valores como gravados.
Períodos longos e muitos sinais são lidos em partes.

## Os objetos dos apps

Todo app se lê do mesmo jeito num notebook: `pc.app(...)` com o nome do app, e os objetos por
tipo. O que cada app oferece está em `pc.apps()`.

```python
link = pc.app("link")
link.blocks()  # uma tabela: o mesmo que link.list("block")
spikes = link.get("block", "dq.spikes")
spikes.run(asset="FIC-101", start="-24h").values()  # no PV da malha, aqui
link.get("algorithm", "flow").run(asset="FIC-101")  # um algoritmo inteiro numa malha
```

Os modelos do Models rodam no Models: `pc.app("models").get("model", id).run(stop=600).wait()`
coloca uma simulação na fila dele, só quando um administrador liga **Simulations from
notebooks** (Settings › Apps › Models, desligado por padrão) e só para editores do Models.
As regras e os alarmes do Alarms são só leitura: `pc.app("alarms").get("alarm", id)` traz as
ocorrências dos últimos 30 dias, ponto de partida de um estudo de desempenho de alarmes. Os
exemplos de cada app mostram o resto: `Examples/Analytics`, `Examples/Models`, `Examples/Historian`,
`Examples/Alarms`.

Um bloco ou algoritmo roda **no notebook** (no seu computador ou neste navegador) com o mesmo
código do Analytics, lendo os dados com o seu acesso. Nada roda no servidor e nada é gravado lá.

## Rodar no seu computador

Para mais memória, pacotes seus, arquivos grandes ou cálculos longos, rode os mesmos notebooks no
JupyterLab do seu computador. Quando um administrador oferece o **kit de Notebooks**, Notebooks ›
Rodar no seu computador o traz para Windows (x64), macOS (Apple silicon) e Linux (x64): de 130 a
180 MB, sem instalação e sem direitos de administrador.

1. **Baixe** o kit do seu sistema e descompacte onde quiser (nos seus Documentos, por exemplo).
   Ele traz Python 3.12, JupyterLab, numpy, pandas, scipy e matplotlib (as versões do navegador)
   e o `plantcraft-notebook`, já apontado para o servidor de onde você baixou (e a autoridade
   certificadora dele, quando a instalação tem a sua própria).
2. **Crie um código de conexão** em Notebooks › Rodar no seu computador (mostrado uma vez só):
   uma linha com o endereço deste PlantCraft, um token seu (só leitura, por 90 dias; você o revoga
   no seu perfil) e a impressão digital da autoridade certificadora da instalação.
3. **Abra o PlantCraft Notebooks** (menu Iniciar, Aplicativos ou o menu do Linux; no zip, dois
   cliques em **Configure token**) e cole o código quando ele pedir. O app confere a autoridade
   certificadora e guarda o token no cofre do sistema (Gerenciador de Credenciais do Windows,
   Keychain do macOS, Secret Service no Linux; sem cofre, num arquivo que só você lê), nunca nos
   arquivos do kit.
4. O JupyterLab abre no seu navegador em `http://127.0.0.1`, que só o seu computador alcança, com
   as pastas `Examples` e `My notebooks`.

Os notebooks ficam em `PlantCraft notebooks` nos seus Documentos, fora do kit, então um kit novo
os mantém. Cada vez que abre, o kit atualiza `Examples` e copia para `My notebooks` os notebooks
que o PlantCraft escreveu para você ("Abrir num notebook"), nunca por cima de um que você editou;
num notebook, `pc.sync()` faz o mesmo. O kit avisa quando o seu token vence em menos de uma
semana e quando o servidor tem um kit mais novo. `%pip install <nome>` adiciona qualquer pacote,
quando o seu computador alcança um índice de pacotes.

Na primeira vez, o Windows pode dizer "O Windows protegeu o computador" (escolha Mais
informações, depois Executar assim mesmo) e o macOS que o script não pode ser aberto (clique com
o botão direito em **Open notebooks.command**, depois Abrir): o kit ainda não é assinado.

**Sem o kit** (ou num Python seu): **baixe** ali o pacote `plantcraft-notebook`, instale com
`pip install` (ele precisa do pandas), **crie um token de acesso** e conecte:

```python
import plantcraft_notebook as pc

pc.connect("https://<servidor>", token="pcat_...")  # ou PLANTCRAFT_URL e PLANTCRAFT_TOKEN
```

Se o seu computador não confia no certificado do servidor, passe `ca="ca-da-empresa.pem"`. As
outras células do notebook rodam sem mudança; a linha `%pip install` da primeira célula é para o
navegador.

## Para administradores

- **Desligado por padrão.** Um administrador liga os Notebooks (Notebooks › Ligar), e toda
  mudança vai para o log de auditoria (`notebooks.settings`, e `notebooks.create` para cada
  notebook que o PlantCraft escreve). `PLANTCRAFT_NOTEBOOKS=off` nas configurações da
  instalação os deixa desligados de vez.
- **O que roda onde.** O código Python roda no navegador de cada pessoa, não no servidor: o
  servidor só entrega os arquivos e responde a API v1 como essa pessoa. Um notebook pesado deixa
  lento o computador dessa pessoa, nunca o servidor da planta.
- **Limites por pessoa.** O que um notebook pede ao servidor (séries, sinais, eventos) tem limite
  por pessoa em Settings › Notebooks: 120 pedidos por minuto e 2 leituras ao mesmo tempo, por padrão.
  Contam todos os pedidos à API v1 feitos com um token de acesso (notebook ou script no
  computador, um limite por token) e as leituras de séries que o navegador da pessoa envia pelo
  proxy. Passado um limite, só essa pessoa recebe `429` com `Retry-After`, e o
  `plantcraft-notebook` espera e pede de novo sozinho (até 4 vezes, no máximo 30 s cada). As
  leituras dos próprios apps (Analytics, Alarms, View), dentro da rede interna, nunca contam, então um
  notebook pesado nunca os deixa lentos. A primeira recusa de cada minuto, por pessoa, vai para o
  log de auditoria (`usage.limited`).
- **O que um notebook pode fazer.** Exatamente o que a pessoa pode fazer no PlantCraft pela API
  v1, pela própria sessão: ler sinais, séries, ativos, resultados e eventos. Ligue os Notebooks
  quando as pessoas forem de confiança para rodar o código que escrevem ou recebem, como qualquer
  ferramenta de análise no computador delas.
- **Segurança.** As páginas dos notebooks (`/notebooks/lite/`) precisam que o navegador rode
  WebAssembly e código que o JupyterLab gera, então a Content-Security-Policy do proxy, só para
  essas páginas, também permite `'unsafe-eval' 'wasm-unsafe-eval'`. Elas continuam sem carregar
  nada de fora do servidor. Tokens de acesso leem a API v1 só enquanto os Notebooks estão ligados,
  e só leem (`GET`, e a leitura de séries `POST /api/v1/series`).
- A imagem leva o JupyterLite e um Pyodide enxuto (cerca de 130 MB), montados por
  `notebooks/build.py` com versões e SHA-256 fixados em `notebooks/pins.json`.
- **O kit** é uma parte opcional do pacote offline (`notebook-kits/`, cerca de 450 MB para os três
  sistemas), montado por `make notebook-kits` (o `make bundle` também os monta; no Mac mini, cada deploy que os muda) (`notebooks/kit/build_kit.py`: python-build-standalone
  e cada wheel fixados por SHA-256 em `notebooks/kit/pins.json` e `requirements.txt`). O download
  fica desligado até um administrador ligá-lo em Settings › Notebooks › Kit for people's computers.
  O PlantCraft acrescenta a cada zip, ao enviá-lo, o endereço do servidor e, com a autoridade
  certificadora local, o certificado raiz dela; nunca um token. Cada download vai para o log de
  auditoria (`notebooks.kit_download`), e cada token de kit também (`assistant_token.create`). Um
  kit roda no computador da pessoa e só lê pela API v1, dentro dos limites acima.
