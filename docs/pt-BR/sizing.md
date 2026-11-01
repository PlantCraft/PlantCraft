# Dimensionamento do servidor

Que máquina a suíte precisa, a partir dos números que medimos. Todo valor abaixo vem do
`make bench-suite` (`ci/bench/suite_bench.py`, relatórios em `docs/bench/results/`) na suíte
0.3.0 com todos os apps ligados, a não ser onde diz "estimativa".

## Resposta curta

| Planta | Sinais arquivados | Malhas / ativos | Pessoas ao mesmo tempo | CPU | RAM | Disco para um ano de histórico e seus backups |
|---|---:|---:|---:|---:|---:|---:|
| Pequena (uma unidade, um piloto) | até 1.000 | até 250 | até 10 | 4 vCPU | 8 GB | 150 GB |
| Média (uma área da planta) | até 8.000 | até 2.000 | até 30 | 4 a 8 vCPU | 16 GB | 1 TB |
| Grande (um site inteiro) | 8.000 a 30.000 | 2.000 a 8.000 | 30 a 100 | 12+ vCPU | 32 GB | 4 TB (estimativa) |

A linha média é a escala "target" do bench, medida numa máquina virtual de 4 vCPU e 16 GB e num
Mac mini de 12 núcleos (Apple silicon). As linhas pequena e grande são estimativas a partir desses
números: rode o bench na sua máquina antes de confiar nelas.

## O que medimos (escala target: 8.000 sinais, 2.050 malhas)

| Etapa | 4 vCPU, 16 GB | Mac mini 12 núcleos |
|---|---:|---:|
| Historian gravando o arquivo | 29.000 valores/s | 52.900 valores/s |
| Uma hora de valores brutos de 8.000 sinais (uma requisição a cada 500) | 4,0 s, p95 478 ms | 3,2 s, p95 710 ms |
| Tendência de 24 h de um sinal, p95 | 21 ms | 17 ms |
| Analytics: uma rodada sobre todas as malhas | 106 s no worker de processamento (50 a 58 s antes dos workers) | 27 s |
| Analytics: verificação da qualidade de todos os sinais | 257 s no worker de processamento (64 s antes dos workers) | 40 s |
| Um dashboard de 24 cartões | 1,8 s | 1,0 s |
| PlantCraft com 4 processos, 16 pessoas clicando ao mesmo tempo | 178 requisições/s | 433 requisições/s, p95 104 ms |
| Pessoas ao mesmo tempo abrindo páginas (5 a 15 s entre páginas, uma consulta pesada aos dados depois de 30 % delas): p95 da página | 10: 1,0 s, 50: 1,6 s, 100: 2,6 s | 10: 2,9 s, 50: 16 s (a demonstração ao vivo; o único processo web do Analytics é o limite) |

Memória de pico por contêiner nessa escala (máquina de 4 vCPU): Analytics 1,0 GB, PlantCraft 1,0 GB,
banco do Historian 1,0 GB, Historian 600 MB, Simulator 320 MB, coletor 190 MB, todos os outros
apps abaixo de 150 MB. Cerca de 4,5 GB no total: 8 GB fica justo e 16 GB deixa folga para o
sistema, o cache de páginas e os backups.

## Disco

- **O arquivo do Historian** é o que cresce. Com os sinais do bench (um valor lido por segundo,
  comprimido por desvio) ele ocupa cerca de 1,4 byte por valor lido: perto de **1 GB por dia
  para 8.000 sinais**, 350 GB por ano. Plantas reais costumam comprimir melhor (sinais estáveis
  guardam poucos valores), e uma varredura a cada 5 s em vez de 1 s divide isso por cinco. A
  retenção de cada ponto (Historian › Configurações) põe o limite.
- **Os backups** também ficam na pasta da instalação: reserve cerca de **o dobro do tamanho do
  Historian** (uma cópia completa por semana e as incrementais diárias), ou aponte os backups
  para outro disco.
- **O resto** (bancos do PlantCraft e dos apps, logs, o pacote) fica abaixo de 10 GB.

A suíte vigia o próprio disco: Administração › Saúde do sistema mostra o espaço livre e, depois
de um dia, em quantos dias o disco enche no ritmo atual. Abaixo de 30 dias ela avisa os
administradores em Mensagens, antes que algo pare.

## Meça a sua máquina

```bash
python3 ci/bench/suite_bench.py --prefix ~/PlantCraft --scale small    # cerca de 5 minutos
python3 ci/bench/suite_bench.py --prefix ~/PlantCraft --scale target   # cerca de 15 a 30 minutos
```

Para pessoas ao mesmo tempo, `python3 ci/bench/load_users.py --prefix ~/PlantCraft` adiciona 10,
30, 60 e 100 pessoas em etapas de 3 minutos e para na primeira etapa cujas páginas levam mais de
3 s no p95. Toda chamada que ele faz é uma leitura. `--heavy 0.3` adiciona uma consulta pesada
aos dados depois de 30 % das páginas (tendências de 7 a 90 dias, 30 ou 90 dias de um sinal, um
dashboard ou relatório de 30 dias), `--visitor` entra como o visitante da demonstração pública, e
`--seed-days 90` primeiro dá 90 dias de histórico a 160 sinais do bench. As telas que ele abre são
gravadas com um navegador por `ci/bench/record_pages.py` (`ci/bench/load_pages.json`).

O relatório vai para `docs/bench/results/` com o nome da máquina; `--compare` põe dois relatórios
lado a lado. Rode com a suíte fora de uso: ele grava dados de teste e os remove no fim.
