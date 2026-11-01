# Exportação

A exportação leva o histórico para fora em arquivos abertos, para um consultor, um colega ou a
sua própria análise em qualquer ferramenta. Um ZIP contém as séries e os metadados da planta.

## Escolher o que exportar

1. **Busque** ativos e tags em uma única caixa: por nome, tag, descrição ou caminho. **Tipo**
   restringe a tags ou a um ou mais tipos de ativo (unidades, equipamentos, malhas e qualquer
   outro tipo da árvore de ativos do PlantCraft); um tipo sozinho lista todos os ativos dele.
2. **Marque** o que você quer e clique em **Adicionar**. Uma tag entra como ela mesma; um ativo
   adiciona todas as tags sob ele, cada uma com o ativo e o papel de onde veio.
3. Repita quantas vezes quiser. A lista abaixo contém o pacote. Ela ordena por qualquer coluna,
   pagina listas longas e tem seu próprio **filtro**. Remova uma tag com o seu **×**, ou marque
   várias (a caixa no cabeçalho marca a página; **Selecionar todos** marca todas as tags que o
   filtro mostra) e clique em **Remover selecionados**. **Limpar** recomeça.

As tags que um ativo cita mas que o Historian não arquiva aparecem como *não arquivado* e são
listadas no manifesto, nunca descartadas em silêncio.

## Salvar uma exportação

Dê um nome à escolha e clique em **Salvar exportação**. As exportações salvas ficam listadas à
esquerda; abra uma e baixe de novo. Um período relativo ("últimas 24 horas") lê até o momento do
download, então "Unidade 100, último dia" traz o dia mais recente a cada vez. **Salvar** a
altera, **Salvar como nova** mantém a antiga. Qualquer pessoa que exporta pode salvar; o autor ou
um editor a altera ou exclui.

## Período e resolução

Um período relativo (das últimas 2 horas aos últimos 30 dias) termina agora; **De – até** aceita
qualquer janela. **Como gravado** traz cada valor arquivado (até 7 dias). Um passo de 1 minuto,
10 minutos, 1 hora ou 1 dia traz um valor por passo em uma grade fixa (até 31 dias), e **Cada
passo guarda** diz qual: a **média** (ponderada no tempo), o **primeiro** ou o **último** valor
gravado no passo, ou o **menor** ou o **maior**. Um passo sem valor gravado fica de fora (a
média mantém o último valor ao longo dele). Um sinal de texto (um modo, um estado) guarda o
último valor do passo para o menor e o maior. O `manifest.json` cita o passo e a agregação. Um
pacote tem até 500 tags.

## Privacidade

**Substituir tags e nomes de ativos por apelidos** transforma cada tag em `S001`, `S002`… e cada
ativo em `A001`…, e deixa nomes e descrições de fora. **Baixar a chave** salva a tabela que
transforma os apelidos de volta: guarde-a à parte; ela nunca vai no pacote.

## O que há dentro

| Arquivo | O que contém |
|---|---|
| `series.csv` | A hora (UTC), depois uma coluna por sinal, com o nome da sua tag (`fonte:tag` quando duas fontes têm a mesma tag); células vazias indicam que não há valor naquela hora |
| `signals.csv` | Todos os sinais: tag, nome, unidade, limites, o ativo e o papel que atende |
| `assets.csv` | Os ativos de onde vieram os sinais, com seus sinais por papel |
| `plant-map.json` | Os ativos e os sinais como um mapa da planta do PlantCraft |
| `manifest.json` | Período, escolhas, o que não pôde ser lido e um SHA-256 de cada arquivo |

Para abri-lo em outro PlantCraft, importe `series.csv` no Historian dele (Importações), depois
importe `plant-map.json` em Administração > Configuração. Toda exportação fica no registro de
auditoria do PlantCraft.
