# O executor Modelica (administradores)

O Models não compila nem roda modelos no seu próprio contêiner. Ele entrega cada verificação,
diagrama, simulação e exportação ao **executor Modelica**, um contêiner separado com o
OpenModelica 1.24, a Modelica Standard Library 4.0.0 e o OMChemSim, a biblioteca aberta de
processos químicos (carregada só para um projeto que a usa):

- **Nenhuma rede** (`network_mode: none`): ele não alcança a planta, o PlantCraft nem a internet.
- **Nenhum segredo**: nenhuma chave de app, nenhum token, nenhum banco de dados.
- Sistema de arquivos raiz **somente leitura**, nenhuma capability do Linux, usuário próprio (uid
  10011).
- **Limites**: CPU, memória e número de processos no arquivo compose; cada trabalho tem um limite
  de tempo (2 minutos para uma verificação ou diagrama, 10 para uma simulação ou exportação), um
  limite de memória e um limite de tamanho de arquivo, e roda no seu próprio grupo de processos,
  que é encerrado no limite de tempo.

O Models e o executor compartilham só uma pasta de trabalhos: o Models escreve um trabalho (os
arquivos do modelo e o que fazer) e o executor responde com os resultados. O Models verifica cada
trabalho antes de ele sair (nenhum código `external`, nenhuma função de arquivo ou de sistema), e o
executor o verifica de novo.

## Os modelos compilados são guardados

Compilar um modelo (o OpenModelica o transforma em um programa C e o compila) toma a maior parte do
tempo de uma simulação: cerca de 5 segundos para os exemplos, contra uma fração de segundo para
rodá-lo. O executor guarda os últimos 32 modelos que compilou para estudos no seu próprio `/tmp`
(nunca na pasta de trabalhos, onde o Models pode escrever): o próximo lote de um estudo, ou o
próximo passo de uma otimização, com os mesmos arquivos, modelo e configurações da simulação, roda
o programa que ele já tem e só troca os parâmetros. Qualquer alteração em um arquivo compila de
novo. Reiniciar o executor o esvazia. `--cache ""` (ou `MODELCRAFT_RUNNER_CACHE=`) desliga isso.

## O estado dele

A Visão geral mostra se o executor está disponível, a versão do OpenModelica e a biblioteca dele. O
executor grava um sinal de vida a cada 10 segundos; quando ele para, o Models avisa, mantém a
edição aberta e recusa verificações e simulações até ele voltar. A fila de simulações fica no banco
de dados: as simulações que estavam rodando quando o Models reiniciou voltam a esperar na fila (uma
exportação de FMU que estava em andamento é marcada como falha).

## Configurações

| Variável | Padrão | Significado |
|---|---|---|
| `MODELCRAFT_RUN_WORKERS` | `2` | Trabalhos entregues ao executor ao mesmo tempo (uma simulação rápida, ou um lote de um estudo). Dimensione pelos núcleos que o executor pode usar: cerca da metade dos da máquina |
| `MODELCRAFT_RUN_BATCH` | `10` | Simulações de um estudo compiladas uma vez e rodadas uma após a outra em um trabalho |
| `MODELCRAFT_STUDY_MAX_RUNS` | `500` | O máximo de simulações que um estudo pode ter (a página de novo estudo avisa acima de 100) |
| `MODELCRAFT_CHECK_SECONDS` | `120` | Limite de tempo de uma verificação ou de um diagrama |
| `MODELCRAFT_RUN_SECONDS` | `600` | Limite de tempo de uma simulação rápida ou de uma exportação, e de uma simulação de estudo que não define nenhum |
| `MODELCRAFT_MAX_RUN_SECONDS` | `21600` | O maior limite de tempo que um estudo pode definir para cada simulação (6 horas) |
| `MODELCRAFT_ALLOW_EXTERNAL` | `false` | Permitir funções `external` (código C) nos modelos. Deixe desligado, a menos que todo editor seja confiável para rodar código no servidor |
