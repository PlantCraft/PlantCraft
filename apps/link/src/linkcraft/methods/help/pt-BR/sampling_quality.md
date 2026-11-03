# Qualidade de amostragem

## O que detecta

Se a fonte grava a malha com finura e regularidade suficientes para julgá-la: o intervalo mediano
entre as amostras gravadas da PV (como o PlantCraft as retorna, antes da grade da análise), seu
percentil 95, o número de lacunas (intervalos muito mais longos que a mediana) e a maior delas.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Dados de
  historiador grosseiros ou comprimidos demais são um dos principais obstáculos práticos que o
  levantamento relata.
- Thornhill, Choudhury e Shah (2004), The impact of compression on data-driven process analyses,
  Journal of Process Control. A pontuação é uma heurística de engenharia.

## Parâmetros

- `recommended_sample_seconds` (padrão 30): o intervalo, em segundos, com que uma malha deste tipo
  deveria ser amostrada; cada múltiplo acima dele custa 60 pontos da pontuação.
- `gap_multiplier` (padrão 2.5): um intervalo mais longo que este múltiplo da mediana conta como
  lacuna; as lacunas custam até 40 pontos.

## Como ler o achado

"A PV foi gravada a cada 10 s (mediana; recomendado até 30 s), com 0 lacunas." O desempenho (100
menos a pontuação) multiplica a saúde da malha.

## Limites

- A compressão do historiador (gravar na mudança) alonga os intervalos de um sinal estável; o
  método os aceita como são, já que esses dados realmente são mais grosseiros para os outros
  métodos.
- Quando uma janela contém valores gravados demais para uma leitura (mais de 200.000 pontos), o
  PlantCraft retorna uma média por passo da grade e o método vê esse passo. Quem chama sem dar
  amostras gravadas recebe os carimbos de tempo da grade; o resultado diz qual deles julgou
  (`timestamp_source`).
