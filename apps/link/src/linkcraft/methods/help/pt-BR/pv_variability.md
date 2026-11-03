# Variabilidade da PV

## O que detecta

Quanto a variável de processo se move em torno da média: desvio padrão, amplitude e coeficiente
de variação ao longo da janela. Reduzir a variabilidade é o que permite a uma planta operar mais
perto dos seus limites.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Variância e desvio
  padrão são medidas básicas de CPM; a pontuação é uma heurística de engenharia.

## Parâmetros

- `variability_tolerance` (padrão 1): o desvio padrão, na unidade da PV, que pontua 100 (o pior);
  a pontuação é o desvio padrão dividido por ela.

## Como ler o achado

"Desvio padrão de 0.42 em torno da média 50.1 (amplitude 2.3)." Compare malhas do mesmo tipo, ou
a mesma malha ao longo do tempo; sozinho, um número diz pouco sem a tolerância definida para o
processo.

## Limites

- A variabilidade sozinha não separa um problema do controlador de uma perturbação do processo ou
  de mudanças de setpoint (a variabilidade inclui os movimentos do setpoint).
- A tolerância é absoluta: defina-a por algoritmo ou malha para PVs que não estão em % da
  amplitude.
