# Resultados

O que cada algoritmo do Analytics concluiu, em cada ativo em que roda: uma linha por algoritmo e
ativo, os piores primeiro. Cada linha mostra o ativo, seu tipo, o algoritmo e sua versão, o estado
nas palavras da suíte (OK, Atenção, Alarme, Desconhecido), a medida do resultado (qualidade,
saúde, pontuação), o achado principal, os rótulos do algoritmo e quando rodou.

Filtre por **algoritmo**, **rótulo**, **tipo de ativo**, **grupo** (o grupo responsável pelo
algoritmo) e **estado**, ou busque por ativo, achado, algoritmo ou rótulo. Cada escolha mostra
quantos resultados manteria. **Limpar filtros** mostra todos os resultados de novo.

**Relatório** imprime em PDF o que o filtro mantém: as contagens por estado e por algoritmo, depois
todos os resultados, os piores primeiro. Um filtro pelo rótulo *malha de controle* dá o relatório do
portfólio de malhas; qualquer outro filtro dá o relatório do que ele mantém.

Abra uma linha para ver o resultado em sua própria página; abra o ativo para ver o resultado de
cada algoritmo nele. Os ativos, malhas incluídas, são cadastrados na página Ativos do PlantCraft: o
Analytics os lê e nunca mantém uma lista própria. A aba **Histórico de execuções** lista todas as
execuções de todos os algoritmos.

## Controladores multivariáveis

A aba **Controladores multivariáveis** lê um controlador avançado de terceiros (APC, MPC) a partir
dos próprios sinais dele e nunca escreve nele. Cadastre-o no PlantCraft como um ativo do tipo
*Multivariable controller* com o sinal `on` (1 quando ligado e controlando) e, dentro dele, um
ativo *Manipulated variable* ou *Controlled variable* por MV e CV, cada um com `value` e, quando o
fornecedor os dá, `lo`, `hi`, `target` (alvo de regime permanente), `status` (1 quando em serviço)
e `shadow_price`. O widget de MV/CV do View lê os mesmos ativos.

Para cada controlador, no último dia, semana ou mês:

- **Ligado**: o tempo em que esteve ligado.
- **MVs em serviço**: o tempo médio em que suas MVs estiveram em serviço enquanto ele estava
  ligado. Uma MV fora de serviço é uma liberdade que o controlador não tem.
- **CVs em um limite**: o tempo médio em que os alvos de suas CVs (os valores, quando não há alvo)
  ficaram dentro da banda de um limite. A banda é a *Banda de limite* da variável, senão 1% da sua
  faixa. Uma CV em um limite é o controlador empurrando a planta contra uma restrição, não uma
  falha.
- O estado é *Alarme* quando o tempo ligado, ou o de MVs em serviço, fica abaixo de 50% e
  *Atenção* abaixo de 90%.

A página de um controlador ordena seus **limites ativos por custo**: as horas em que cada um esteve
ativo, o preço-sombra do próprio controlador (a média enquanto ativo) e o **valor de 1% a mais de
faixa**, o preço-sombra vezes 1% da faixa da variável: quanto valeria mover esse limite, na unidade
de custo do controlador. Um limite sem preço-sombra é ordenado pelas horas. O relatório semanal
traz as mesmas duas tabelas, e o widget *Analytics: controladores multivariáveis* mostra cada
controlador na Visão geral e no Desk.
