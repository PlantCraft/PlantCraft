# Curso da válvula

## O que detecta

Quanto a válvula trabalha: o movimento acumulado da saída por hora (curso) e o número de mudanças
de sentido por hora (reversões). Curso e reversões em excesso desgastam gaxetas e atuadores e
costumam vir de ruído ou de sintonia agressiva.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Curso e reversões
  da válvula são indicadores padrão da saúde da válvula; os limiares são heurísticas de
  engenharia.

## Parâmetros

- `max_travel_per_hour` (padrão 200): o curso acumulado da saída, em % por hora, que pontua 100.
  Malhas rápidas (vazão) recebem mais, e lentas ou de média recebem menos, pelo seu tipo de malha.
- `max_reversals_per_hour` (padrão 60): o número de mudanças de sentido por hora que pontua 100.
- `reversal_epsilon` (padrão 0.05): o menor movimento da saída, em %, contado ao procurar uma
  mudança de sentido.

## Como ler o achado

"A saída percorreu 320% por hora, com 45 reversões por hora." A pontuação é a pior das duas taxas.
Curso alto com uma PV ruidosa aponta para ruído chegando à válvula (filtro, ação derivativa);
curso alto com uma oscilação, para sintonia ou agarramento (stiction).

## Limites

- A saída é o comando do controlador, não a posição da haste.
- Contado na grade da análise: a média em cada passo da grade esconde movimentos rápidos, e no
  máximo uma reversão por amostra da grade pode ser contada.
