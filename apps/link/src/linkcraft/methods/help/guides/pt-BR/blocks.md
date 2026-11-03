# Blocos

Todos os blocos que um algoritmo pode usar, em sete bibliotecas: escolha uma biblioteca à esquerda
para ver seus blocos.

- **Entradas**: os sinais do ativo por papel (PV, SP, OP, modo…), e os resultados que a Qualidade
  dos sinais já deu a eles.
- **Qualidade de dados**: a verificação dos dados da malha (roda primeiro em toda malha; os métodos
  depois dela não rodam com dados que ela rejeita) e as verificações que a Qualidade dos sinais
  roda em cada sinal.
- **Transformações**: erro, filtros, remoção de tendência, diferença, recorte, atraso.
- **Desempenho de malhas de controle**: rastreamento, oscilação, válvula, saturação, ruído e modo de
  operação; cada um dá um resultado e seus números principais.
- **Modelos**: um bloco por modelo de processo publicado (FMU), que o roda sobre os sinais do ativo
  e dá o que ele prevê e o resíduo em relação à planta; o bloco de desvio (T²), que diz quão longe
  a planta está do modelo; e quando a unidade está em operação.
- **Lógica**: pior de, média, regra, limites.
- **Saídas**: saúde da malha, um resultado no ativo, uma mensagem, o resultado de um sinal.

Um site adiciona suas próprias bibliotecas com **Nova biblioteca**, abaixo das bibliotecas ou ao
lado do campo Biblioteca no formulário de um bloco; elas são listadas depois das do próprio
Analytics.

Abra um bloco para ver o que ele faz, como lê-lo, suas entradas e saídas, seus parâmetros e os
padrões deles neste site, suas premissas, limites e referências, e seu código-fonte. Os
administradores alteram os parâmetros padrão de um método na página dele; um tipo de malha, um
algoritmo ou uma malha ainda podem substituí-los.

**Duplicar**, ao lado de Baixar o arquivo, inicia um novo bloco a partir dele, na biblioteca que
você escolher. Um bloco deste site recebe sua próxima versão com **Nova versão**, na aba Versões;
um bloco que acompanha o PlantCraft mostra ali um cadeado fechado: ele muda com o PlantCraft, então
duplique-o para fazer o seu.
