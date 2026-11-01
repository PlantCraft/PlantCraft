# Configurações

Os administradores definem como os sinais são lidos, comprimidos e guardados. As configurações
vêm em três níveis, e o mais específico prevalece:

1. **Geral** (esta página): todos os sinais de todas as fontes.
2. **Fonte**: uma fonte pode definir o próprio valor para os seus sinais (Fontes, Editar,
   "Configurações dos sinais desta fonte"). Os campos vazios usam o valor geral.
3. **Sinal**: um sinal pode definir o próprio valor (na página dele, "Coleta e compressão"). Os
   campos vazios usam o valor da fonte, senão o geral.

| Configuração | Padrão geral | Significado |
|---|---|---|
| Retenção (valores brutos) | 400 dias | Valores mais antigos do que isto são excluídos, de hora em hora (no PostgreSQL, um mês passado cujos valores já passaram todos da retenção é descartado de uma vez) |
| Agregações por hora | 1825 dias (5 anos) | A média, o menor e o maior valor de cada hora, guardados depois que os valores brutos se vão; só geral |
| Agregações por dia | para sempre (0) | As de cada dia UTC, a partir das agregações por hora; só geral |
| Agregações por mês | para sempre (0) | As de cada mês UTC, a partir das agregações por dia; só geral |
| Varredura | 1 s | Segundos entre duas leituras |
| Desvio | 0,1 % | Da faixa do sinal quando a faixa é conhecida, senão do valor (cada valor arquivado começa um segmento mantido dentro dessa parcela dele; perto de 0, quase toda mudança é guardada). Um sinal o define em unidades de engenharia |
| Intervalo máximo | 3600 s | Um valor é arquivado pelo menos com esta frequência, mesmo em um sinal constante |

A página de um sinal diz o que está em vigor e de onde vem, por exemplo "400 dias, das
configurações gerais". Uma alteração em qualquer nível chega ao coletor em segundos; os sinais
que definem o próprio valor não mudam. Cada alteração é escrita no registro de auditoria do
PlantCraft.

## Agregações e o disco

As tendências de horas inteiras, dias ou mais, e a média, o menor e o maior valor de uma janela,
leem as agregações em vez de cada valor arquivado: um ano como tendência diária lê 365 linhas
diárias. As agregações têm a própria retenção, então os valores brutos podem ser guardados por
alguns meses e os anos da planta continuam virando tendência, com suas médias e extremos. Um
nível é sempre guardado pelo menos tanto quanto os valores brutos e os níveis mais finos (um mais
curto seria apenas somado de novo a partir deles), e um sinal guardado para sempre guarda suas
agregações para sempre.

**Disco por retenção**, na página Retenção e coleta, mostra o que cada nível guarda agora e o que
vai guardar quando todos os sinais tiverem a retenção completa, no ritmo dos valores arquivados
nas últimas 24 h (por ano, para o que é guardado para sempre). Uma linha de agregação por hora
ocupa cerca de 125 bytes em disco e uma por dia ou por mês, 150: um ano de agregações por hora de
um sinal dá cerca de 1,1 MB, de agregações por dia, 55 KB.
