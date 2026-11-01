# Sinais

Todos os sinais que o PlantCraft conhece, com o último resultado do algoritmo Qualidade dos
sinais. Filtre por estado, por fonte, por uma verificação que o sinalizou, ou busque por id e
nome. Abra um sinal para ver por que recebeu seu resultado.

- **Bom** (mostrado no PlantCraft como *OK*): todas as verificações passaram.
- **Suspeito** (*Atenção*): pelo menos uma verificação alertou; os dados ainda são utilizáveis.
- **Ruim** (*Alarme*): pelo menos uma verificação falhou; malhas e outros apps não devem confiar
  nesses dados.
- **Desconhecido**: nenhuma verificação conseguiu julgar o sinal (amostras de menos, ilegível, só
  texto).

A qualidade é 100 menos a pontuação da pior verificação: 100 é perfeito, abaixo de 25 é
inutilizável.

Os sinais vêm do catálogo do PlantCraft pela API v1; o Analytics nunca mantém uma lista própria de
tags. Sinais derivados (séries que um app calculou, como as pontuações de qualidade e de saúde do
próprio Analytics) não são verificados. Um sinal que desaparece do PlantCraft é marcado como
ausente e mantido, para que seu histórico permaneça.
