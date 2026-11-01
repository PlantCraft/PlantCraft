# Fontes

Uma fonte é um sistema da planta que o Historian lê: um servidor OPC UA, um PI Web API, arquivos
CSV, ou, por meio do gateway, um broker MQTT, um dispositivo Modbus TCP ou um banco de dados SQL,
ou os nós de borda de um broker Sparkplug B.
Os sinais calculados (veja Sinais) têm uma fonte própria, `calc`, criada com o primeiro deles.
Os sinais derivados dos apps têm uma fonte própria, que só o app escreve. Só administradores
adicionam, alteram ou removem fontes.

- **Endpoint**: `opc.tcp://host:port/path`, a URL base do PI Web API, ou o arquivo ou padrão CSV
  (`/csv/lab/*.csv`).
  O Historian só lê: Read, Browse e HistoryRead do OPC UA, GET do PI Web API. Ele nunca escreve
  em um sistema da planta.
- **Acesso**: anônimo, ou um nome de usuário com senha. Uma senha digitada é guardada
  criptografada e nunca mais exibida; ela também pode vir de uma variável de ambiente
  `HISTCRAFT_SECRET_*`.
- **Segurança** (OPC UA): Nenhuma, Assinar, ou Assinar e criptografar, com a política que o
  servidor oferece (Basic256Sha256, Aes128_Sha256_RsaOaep ou Aes256_Sha256_RsaPss). Baixe o
  certificado do Historian no formulário e adicione-o à lista de confiáveis do servidor. O
  primeiro **Testar** mostra o certificado do servidor (seu SHA-256, titular e datas): compare-o
  com o que o administrador do servidor vê, depois clique em **Confiar**. Daí em diante, um
  servidor que apresentar outro certificado é recusado.
- **Qualidade**: o OPC UA e o PI informam a qualidade de cada valor. Os valores incertos são
  arquivados e sombreados na tendência do sinal; os valores ruins são lacunas. Com OPC UA, o
  código de status também é guardado (como `UncertainLastUsableValue` ou `BadSensorFailure`),
  assim como os bits de limite (um valor preso no limite inferior ou superior, ou constante),
  então um valor bom que atinge o limite superior é arquivado onde atingiu. Os arquivos CSV só
  informam qualidade em uma coluna `quality` (formato longo); as séries dos apps não informam
  nenhuma: seus valores contam como bons.
- **Modo**: de onde vem o histórico dos seus sinais (lido da fonte, arquivado aqui, ou os dois),
  a menos que um sinal defina o próprio.
- **Configurações dos sinais desta fonte**: retenção, varredura, desvio (% da faixa) e intervalo
  máximo para todos os sinais da fonte. Os campos vazios usam as configurações gerais; o valor
  próprio de um sinal prevalece sobre o da fonte (veja Configurações).
- **Integração**: quem responde pela fonte e com que frequência ela precisa entregar dados. Os
  **Responsáveis** são pessoas ou grupos do PlantCraft (`user:ana, group:automation`);
  **Contato** diz como falar com a equipe que cuida da conexão; **Intervalo esperado** é com que
  frequência um valor novo precisa chegar em pelo menos um dos seus sinais (vazio: não vigiado).
  Quando a fonte desconecta, ou não envia nada por mais tempo do que o esperado (*Fonte
  atrasada*), o PlantCraft avisa os responsáveis nas Mensagens e por e-mail, com o contato, e
  resolve a mensagem quando a fonte volta. A página da fonte lista seus responsáveis e o
  **histórico** dos seus estados (conectada, desconectada), guardado por 90 dias.
- **Testar** pede ao coletor que se conecte uma vez e informe a resposta do servidor.
- **Arquivos CSV**: um arquivo, ou um padrão na última parte do caminho (`/csv/lab/*.csv`), que
  outra aplicação continua escrevendo. O coletor o confere a cada **Conferir a cada (minutos)**
  (padrão 5), arquiva as linhas depois do último valor arquivado e os arquivos novos, e nunca os
  move nem os altera. Seus sinais existem só no arquivo. Os formatos e as regras de horário são
  os de Importações; um arquivo carregado uma vez pertence a **Importações**. Os arquivos lidos
  do jeito que você os conferiu (colunas, formato da hora), com cada tag virando um sinal, são
  uma importação que **se repete a partir de uma pasta**: ela também é listada aqui, marcada
  como **Repetições**.
- Um app incorporado a outro (Twin, CPMCraft e DataCraft ao Analytics) aparece como "App
  desativado": nada mais escreve suas séries, e um administrador pode removê-lo com seus sinais.
- **Assinar as mudanças** (OPC UA, desligado por padrão): o servidor informa cada mudança,
  amostrada no período de varredura do sinal, em vez de o Historian ler a cada varredura. Um
  valor que se mantém é tomado de novo a cada período de varredura, então a compressão funciona
  como com uma varredura. Um nó que o servidor não monitora é lido a cada varredura. O Historian
  só monitora valores; não altera nada no servidor.
- **Navegar** lista as variáveis do servidor com suas unidades e faixas, para que você adicione
  muitos sinais de uma vez. Os sinais já arquivados ficam marcados. Deixe a varredura e o desvio
  vazios para usar as configurações da fonte ou as gerais; uma variável para a qual o servidor
  não informa faixa é então comprimida por essa parcela do seu valor, em vez da faixa.
- **MQTT, Modbus e SQL** são lidos pelo gateway (Telegraf), que envia cada valor ao coletor; seus
  sinais existem só no arquivo. MQTT: o broker, os tópicos (`+` um nível, `#` o resto) e se uma
  mensagem é um número ou JSON. Modbus TCP: o dispositivo, seu slave id e cada registrador ou
  coil a ler (tipo, endereço a partir de 0, tipo de dado, ordem de bytes, escala; um valor de 64
  bits cita os oito bytes, de ABCDEFGH a GHEFCDAB). SQL: o banco de dados, sua string de conexão
  com `{password}` onde vai a senha, e um SELECT rodado a cada período de varredura (10 s quando
  vazio) por um usuário que só pode ler. A coluna de hora e as colunas de tag não são sinais
  próprios. Só as linhas mais novas do que o último valor de um sinal são arquivadas.
  **Navegar** lista o que o gateway enviou; uma fonte muda por 60 s aparece como Desconectada.
  Armazenar e encaminhar: os valores que o gateway lê enquanto o coletor está fora esperam no
  buffer em disco dele e chegam em ordem quando o coletor volta, também depois de um reinício do
  gateway; um lote enviado duas vezes é aproveitado uma vez. A saúde da suíte dá um aviso quando
  mais de 64 MB estão esperando.
- **Sparkplug B** é lido pelo coletor, que assina o broker (`tcp://` ou `ssl://`) como um host
  que só escuta: births, dados e deaths de um grupo, ou de todos quando o grupo está vazio. Ele
  nunca publica, então não é um host primário e nunca pede a um nó que nasça de novo. Com
  *Adicionar sinais a partir dos births* ligado, cada métrica que um birth descreve vira um sinal
  sozinha (tag `<group>.<node>.<device>.<metric>`, com seu tipo e unidade); senão, **Navegar** as
  lista para adicionar. Um death marca como ruins os valores do nó ou do dispositivo. Um nó que
  nasceu antes de o Historian se conectar envia dados por alias que nenhum birth nomeou: o estado
  dele os conta, e eles são lidos a partir do próximo birth do nó (reinicie-o para tê-los agora).
- **Resultados de laboratório (LIMS)**: uma fonte SQL marcada assim grava cada linha como um
  resultado de laboratório na sua hora de amostragem, com seu status (incerto até ser aprovado,
  ruim quando rejeitado) e as horas em que chegou ao laboratório e em que foi aprovado. Uma linha
  lida de novo sem mudança não é regravada.
