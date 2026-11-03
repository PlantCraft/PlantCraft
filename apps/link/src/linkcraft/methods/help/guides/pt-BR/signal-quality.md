# Algoritmo Qualidade dos sinais

Um algoritmo do sistema: lê todos os sinais habilitados em uma janela (24 horas por padrão) e roda
neles os métodos de Qualidade de dados, com uma cadência (a cada 15 minutos por padrão). Cada
execução é uma execução, listada em Resultados > Histórico de execuções com suas contagens e
duração, e na página Resultados do PlantCraft.

Os administradores alteram a janela, o monitor, quais verificações rodam por padrão e seus
parâmetros padrão na página do algoritmo; as configurações próprias de um sinal ainda prevalecem.

As execuções usam a chave de app do Analytics, criada por um administrador no PlantCraft. Depois de
cada execução o Analytics publica seus resultados no PlantCraft: `linkcraft.signal_quality` em
cada sinal e em cada ativo (o pior dos seus sinais), e a série derivada
`app-linkcraft:<signal>.quality`.

Os métodos de malha leem esses resultados: uma malha cuja PV ou OP está ruim não é analisada (é
informada como bloqueada pela Qualidade dos sinais), e um sinal suspeito é anotado no achado da
malha.

## As verificações

- **Disponibilidade e lacunas**, **Atualidade**: a fonte envia valores, e recentemente.
- **Qualidade na fonte**: quanto da janela a própria fonte marcou como ruim, substituído ou
  incerto (OPC UA, PI e Canary guardam uma qualidade com cada valor). Tempo ruim ou substituído
  acima de 1% é atenção, acima de 5% torna os dados inutilizáveis; tempo incerto é no máximo
  atenção. Em uma fonte sem qualidade, não se aplica.
- **Valor congelado**, **Picos**, **Ruído**, **Resolução e compressão**, **Deriva**.
- **Fora da faixa**: valores fora dos limites do sinal.
- **Taxa de variação**: variações, medidas em pelo menos um minuto, mais rápidas do que o processo
  consegue se mover. O limite é o do próprio sinal (por minuto), ou metade da sua faixa por minuto
  por padrão.
- **Níveis de falha do transmissor (NE 43)**: um sinal de 4-20 mA lido na sua faixa como faz a
  NAMUR NE 43. De 3,8 a 20,5 mA é medição; 3,6 mA ou menos, ou 21 mA ou mais, é o transmissor
  informando a própria falha. Qualquer nível de falha é atenção, e acima de 1% dos valores é ruim.

Fora da faixa, Taxa de variação e NE 43 precisam dos limites do sinal (a taxa pode ter um limite
próprio); sem eles, não se aplicam.
