# Sinais

Um sinal é uma tag de uma fonte que o Historian lê ou arquiva. Seu id de sinal,
`<id da fonte>:<tag>`, é o nome que os apps veem.

| Configuração | Significado |
|---|---|
| Varredura | Segundos entre duas leituras |
| Desvio | Tolerância de compressão em unidades de engenharia: a tendência reconstruída nunca se afasta mais do que isto de um valor lido. 0 guarda toda mudança |
| Intervalo máximo | Um valor é arquivado pelo menos com esta frequência, mesmo em um sinal constante |
| Retenção | Dias em que o arquivo guarda seus valores |
| Degrau | Estados liga/desliga e setpoints movidos à mão: mantidos até a próxima mudança, nunca interpolados |
| Tipo | Número ou texto |

Varredura, desvio, intervalo máximo e retenção podem ficar vazios: o sinal então usa o valor da
sua fonte, senão as configurações gerais. Abaixo de cada campo, a página mostra o valor em vigor
e de onde vem ("definido neste sinal", "da fonte", "das configurações gerais").

A instalação pode limitar quantos sinais o Historian grava (`MAX_SIGNALS` no arquivo de
instalação do PlantCraft). Os sinais adicionados além do limite são ignorados, e a resposta diz
por quê. As séries que os apps escrevem não contam.

A página do sinal mostra sua tendência em qualquer intervalo e os bytes que ele ocupa em disco.
Excluir um sinal remove também o seu arquivo (só administradores).

O filtro **Tipo** da tabela (na coluna Varredura e desvio) mostra um tipo de sinal: lido da
planta, calculado, importado, escrito por um app ou pelo PlantCraft.

## Notas

A página de um sinal lista as notas escritas nele no período exibido: o que aconteceu e os
valores não dizem ("analisador recalibrado", "bomba B em manual das 14:00 às 15:30"). Os editores
adicionam uma em um instante ou ao longo de um intervalo, e removem as próprias (os
administradores, qualquer uma). Cada nota também é informada ao PlantCraft como um evento (*Nota
em um sinal*), para que Eventos, o Alarms e o assistente a vejam. Scripts e outros apps as leem e
escrevem com `GET` e `POST /api/v1/annotations`.

## Valores editados

Um editor pode inserir um valor onde não havia nenhum, alterar um ou excluir um (uma leitura
feita enquanto o sensor estava em calibração, um valor digitado à mão), sempre com um motivo. O
valor lido passa a levar sua marca (*inserido*, *editado* ou *excluído*), o valor substituído fica
guardado com quem o alterou, quando e por quê (a lista em **Valores editados**, ou
`GET /api/v1/edits/{signal}`), e cada edição fica no registro de auditoria do PlantCraft. Os
sinais que um app escreve são alterados nesse app. Scripts usam `POST /api/v1/edits`.

## A lista de sinais em uma planilha

**Exportar lista de sinais**, na página Exportações, escreve cada sinal com a sua própria
configuração: `source_id`, `tag`, `address`, `name`, `description`, `unit`, `kind`, `step`,
`low`, `high`, `mode`, `scan_seconds`, `deviation`, `max_seconds`, `retention_days`, `enabled`.
Uma célula de configuração vazia significa "herdar" da fonte ou das configurações gerais.

**Importar lista de sinais** (editores), na página Importações, lê um arquivo assim, separado por
vírgulas, pontos e vírgulas ou tabulações. Só `source_id` e `tag` são obrigatórios; as colunas
deixadas de fora mantêm o que os sinais têm. Uma linha cuja fonte e tag existem altera esse
sinal; qualquer outra linha adiciona um. O Historian primeiro mostra o que o arquivo adiciona e
altera e lista cada linha com problema; nada é importado até todas as linhas estarem certas. Um
endereço ou um tipo não pode mudar: remova o sinal e adicione-o de novo.

## Sinais calculados

**Adicionar sinal calculado** cria um sinal a partir de outros com uma fórmula: uma conversão de
unidade, uma soma de vazões, uma condição, um totalizador. Seu sinal é `calc:<tag>` e ele é
arquivado, comprimido e exibido em tendência como qualquer sinal; os apps e as exportações o leem
do mesmo jeito.

- Os sinais são escritos `[fonte:tag]`, por exemplo `[plant:FI-100.PV] * 3.6`. Uma fórmula pode
  usar números, `+ - * / ** %`, comparações (`< <= > >= == !=`, verdadeiro é 1), `and`, `or`,
  `not` e as funções abs, min, max, sqrt, exp, log, log10, round, clip e if:
  `if([plant:XV-1.PV] > 0.5, [plant:FI-1.PV], 0)`.
- Um **totalizador** é a fórmula inteira: `total([plant:FI-100.PV], per="h", reset="day")`
  integra uma taxa dada por segundo, minuto, hora ou dia (`per` = s, min, h, d) e reinicia a
  cada hora, dia ou mês em UTC, ou nunca (`reset` = hour, day, month, none). O tempo em que uma
  entrada não tem valor não soma nada; depois de um reinício do coletor, o total continua a
  partir do seu último valor arquivado no mesmo período.
- As entradas são sinais arquivados aqui: sinais OPC UA no modo archive ou both, ou outros sinais
  calculados (uma varredura depois). Os sinais PI Web API e CSV só são lidos sob demanda, então
  uma fórmula não consegue acompanhá-los. Uma fórmula nunca lê a si mesma, nem diretamente nem
  por meio de outras.
- O coletor avalia cada fórmula na varredura do sinal com os últimos valores das suas entradas.
  Qualquer entrada ruim, desconectada ou ausente gera uma lacuna; qualquer entrada incerta torna
  o resultado incerto. As fontes que não informam qualidade contam como boas.
- A fórmula pode mudar na página do sinal ou no CSV da lista de sinais (coluna `address`).
