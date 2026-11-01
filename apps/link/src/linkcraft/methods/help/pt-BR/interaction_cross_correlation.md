# Interação entre malhas

## O que detecta

Se a malha se move junto com um segundo sinal (a PV de outra malha, uma carga ou um coletor de
utilidades): a maior correlação absoluta entre os dois em uma faixa de defasagens, com a
defasagem em que ela ocorre. Uma correlação forte é uma pista de uma perturbação compartilhada ou
de uma interação.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control.
- Thornhill e Hägglund (1997), Detection and diagnosis of oscillation in control loops: uma
  oscilação de toda a planta aparece em várias malhas ao mesmo tempo.

## Parâmetros

- `max_lag_samples` (padrão 60): o maior deslocamento, em amostras da grade, tentado em cada
  sentido.
- `correlation_threshold` (padrão 0.5): a correlação absoluta que pontua 100; a pontuação é a
  melhor correlação dividida por ela.

## Como ler o achado

"Correlação de 0.82 com o sinal secundário, com defasagem de 4 min." O sinal diz se eles se
movem juntos ou em oposição; a defasagem diz qual vem antes. Confira a topologia do processo antes
de culpar uma malha: correlação não prova causalidade.

## Limites

- Precisa de um sinal `secondary` na malha; sem ele o método informa dados insuficientes.
- Perturbações comuns produzem correlação sem nenhuma interação.
