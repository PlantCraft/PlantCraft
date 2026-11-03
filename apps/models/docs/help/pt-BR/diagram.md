# Desenhando diagramas

A aba **Diagrama** desenha a classe selecionada: cada componente é desenhado com o ícone da sua
biblioteca, na posição que a anotação `Placement` dele indica, e cada equação `connect` com a sua
linha.

Toda alteração feita no diagrama é escrita no texto da classe, do jeito que você mesmo a
escreveria, e o diagrama é desenhado de novo a partir do texto. O texto continua sendo a única
fonte: o que você desenha é o que você pode ler, comparar e manter no controle de versão.

| Para | Faça |
|---|---|
| Adicionar um componente | Abra **Biblioteca** à esquerda, encontre a classe (busque, ou abra os pacotes) e arraste-a para o diagrama; ou arraste um modelo ou bloco da árvore **Arquivos** |
| Mover um componente | Arraste-o |
| Girá-lo um quarto de volta | Selecione-o e pressione **R** (ou o botão de girar) |
| Excluir um componente | Selecione-o e pressione **Delete**; as conexões dele vão junto |
| Conectar dois conectores | Arraste de um conector até o outro (o cursor vira uma cruz sobre um conector) |
| Excluir uma conexão | Clique na linha dela e pressione **Delete** |
| Alterar um parâmetro | Selecione o componente; os parâmetros dele ficam à direita. Escreva um valor e clique em **Aplicar**; um valor vazio remove o seu e o padrão volta a valer |
| Zoom, deslocar | Roda do mouse; arraste o fundo vazio |

Um novo componente ganha um nome a partir da classe (`gain`, `gain1`...). Para renomeá-lo,
altere-o no texto, junto com as conexões dele.

Os conectores só se conectam quando são compatíveis (um `RealOutput` com um `RealInput`, uma porta
de fluido com uma porta de fluido...). O diagrama escreve o `connect`; **Verificar** diz se os dois
não combinam.

Os componentes herdados (de um `extends`) são desenhados, mas não são movidos: altere-os na classe
base.

## Uma planta com seus próprios componentes

Construa as partes uma vez e depois conecte-as, como no OpenModelica:

1. **Nova classe**, partindo de um componente: um **bloco de sinal** (entrada `u`, saída `y`), um
   **componente térmico** (uma porta de calor) ou um **componente elétrico** (dois pinos). Cada um
   vem com seus conectores, parâmetros, uma equação para alterar e um ícone.
2. **Nova classe**, partindo de um **Sistema**: um diagrama vazio com um `experiment`. Um diagrama
   vazio avisa isso, com um botão que abre a **Biblioteca**.
3. Abra o **Diagrama** do sistema e arraste seus componentes da árvore **Arquivos** (e fontes,
   sensores ou controladores da **Biblioteca**). Conecte-os e clique em **Simular** no sistema:
   todos os componentes rodam juntos.

Um componente alterado depois altera todo sistema que o usa. Uma classe não pode ser solta dentro
dela mesma.

## A biblioteca

**Biblioteca** lista a Modelica Standard Library 4.0.0. Clique em uma classe para ler o ícone, os
parâmetros, a documentação e o texto dela; arraste-a para um diagrama para usá-la. Os pacotes de
documentação e as classes internas não são listados.

## Documentação

A aba **Documentação** mostra a anotação `Documentation(info = "<html>...</html>")` da classe. Ela
é mostrada sem nenhum script e sem links para fora da página.
