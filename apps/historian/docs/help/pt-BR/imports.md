# Importações

**Importações** carrega arquivos CSV e Excel no arquivo: análises de laboratório, uma exportação
de outro sistema, uma planilha. Uma importação lê os próximos arquivos do mesmo jeito, e pode
**repetir a partir de uma pasta**: cada arquivo novo ali é lido todo dia, ou com mais
frequência, para os mesmos sinais.

## Importar um arquivo

1. Clique em **Importar CSV** e escolha o arquivo (até 200 MB). O Historian o confere na hora e
   ainda não grava nada.
2. Defina o **fuso horário** dos horários escritos sem offset. Os horários com offset ou `Z` são
   lidos como escritos. Tudo é armazenado em UTC.
3. Leia a conferência: formato, período, linhas, valores e sinais, depois os **erros** (o arquivo
   não pode ser importado) e as **observações** (pode, mas olhe antes). Cada problema lista suas
   linhas.
4. Dê um nome à importação e clique em **Importar**. O coletor grava os valores, um arquivo por
   vez; o status mostra **Esperando** enquanto o arquivo está na fila, depois **Gravando
   valores** com uma barra de andamento. A **Fila** da suíte mostra o mesmo. O arquivo enviado é
   então excluído: os valores ficam no arquivo. Um arquivo ainda em espera pode ser cancelado
   (**Cancelar o arquivo em espera**); um que está sendo gravado não é interrompido.

## O próximo arquivo, e repetir a partir de uma pasta

**Importar o próximo arquivo** lê um arquivo novo do jeito que o último arquivo da importação foi
lido (separador, colunas, formato da hora, fuso horário) para a mesma importação: tags novas
viram sinais, e valores em um horário já importado são substituídos.

**Repetir a partir de uma pasta** faz isso sozinho. Informe um arquivo, ou um padrão como
`/csv/lab/*.csv`, dentro das pastas que o administrador liberou para fontes CSV
(`HISTCRAFT_CSV_DIRS`), e com que frequência conferi-lo (de a cada 15 minutos a todo dia). Cada
arquivo ali que é novo ou mudou é lido e gravado, e aparece na fila enquanto isso; um arquivo que
não mudou não é lido de novo, e um arquivo com erros é ignorado e citado no status da
importação. Os arquivos são só lidos, nunca movidos nem alterados. Os sinais mantêm seus nomes
(`import-3:LAB-101.DENSITY`), então os gráficos e algoritmos que os usam continuam funcionando.
Uma importação que se repete também é listada em Fontes. **Parar de repetir** mantém todos os
valores gravados.

## Formatos

| Formato | Colunas |
| --- | --- |
| Largo | A hora, depois uma coluna por tag. |
| Longo | A hora, a tag, o valor e, opcionalmente, a qualidade (`good`, `uncertain`, `substituted`, `bad`). |

O separador (`,` `;` tabulação `|`) e uma vírgula decimal são detectados a partir do arquivo. Os
horários podem ser ISO 8601, `dd/mm/yyyy hh:mm` (`mm/dd` quando uma primeira parte passa de 12)
ou epoch Unix em segundos ou milissegundos. Células vazias e marcadores como `NA`, `#N/A`, `null`
ou `-` são lacunas. Uma coluna que é quase toda texto vira um sinal de texto.

Os **erros** bloqueiam a importação: horários ilegíveis, texto em uma coluna numérica, linhas sem
tag, qualidades desconhecidas, colunas duplicadas ou sem nome. As **observações** não bloqueiam:
horários repetidos (o último valor prevalece), horários mais de um dia à frente, como uma data
dia/mês foi lida, um arquivo já importado antes.

## Sinais e guarda

Cada importação é uma fonte própria (`import-1`, `import-2`, ...) com um sinal por tag, no modo
archive. Seus valores são guardados até a importação ser excluída, a menos que um sinal receba
uma retenção própria. A lista mantém cada importação com quem a carregou e quando.

**Excluir** remove a importação, seus sinais e todos os valores que ela trouxe, depois que você
digita o id dela. Não pode ser desfeito. Só editores importam e excluem.
