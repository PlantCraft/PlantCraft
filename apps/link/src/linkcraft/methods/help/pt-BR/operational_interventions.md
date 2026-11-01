# Intervenções do operador

## O que detecta

Com que frequência pessoas (ou uma camada supervisória) intervêm na malha: mudanças de setpoint
mais trocas do modo do controlador, escaladas para uma janela de referência. Uma malha que precisa
de atenção constante não está cumprindo seu papel, mesmo quando o erro parece pequeno.

## Referência

- Bauer, Horch, Xie, Jelali e Thornhill (2016), The current state of control loop performance
  monitoring: a survey of application in industry, Journal of Process Control. Contar as
  intervenções do operador é uma medida industrial comum.
- Jelali (2006), An overview of control performance assessment technology and industrial
  applications, Control Engineering Practice. Lista as intervenções do operador entre os KPIs
  práticos de CPA industrial. Os limiares são uma heurística de engenharia; ajuste-os por planta.

## Parâmetros

- `sp_change_threshold` (padrão 0.1): o menor movimento do setpoint, na unidade da PV, contado
  como intervenção; movimentos menores são ruído ou arredondamento.
- `reference_hours` (padrão 12): a janela, em horas, para a qual a contagem é escalada (um turno).
- `full_performance_max` (padrão 2): até este número de intervenções por janela de referência o
  critério pontua 100%.
- `zero_performance_min` (padrão 12): a partir deste número de intervenções por janela de
  referência o critério pontua 0%; entre os dois cai linearmente.

## Como ler o achado

"3 mudanças de setpoint e 1 troca de modo na janela, equivalente a 2 intervenções a cada 12 h."
Isto é contexto: é mostrado ao lado da pontuação de saúde e nunca multiplicado nela, porque um
operador atarefado não deve fazer um bom controlador parecer ruim. Muitas intervenções em uma malha
com boa pontuação sugerem que os operadores não confiam nela, ou que o setpoint é conduzido por uma
receita ou por um APC.

## Limites

- Receitas, APC, partidas e trocas de grade movem setpoints de propósito.
- Precisa de SP ou de modo; sem nenhum dos dois, informa dados insuficientes.
- Uma camada supervisória que escreve o setpoint a cada amostra (o secundário de uma cascata) conta
  cada escrita; não o use em secundários de cascata.
