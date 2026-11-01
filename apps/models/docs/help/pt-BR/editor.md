# Escrevendo código Modelica

**Código**, na página de um modelo, abre o texto Modelica dele, e **Nova biblioteca de blocos**, na
página Blocos, abre o de uma biblioteca. A aba **Texto** é um editor Modelica:

- **Realce** de palavras-chave, tipos, números, strings e comentários.
- **Completar**: comece a digitar o nome de uma classe (`Modelica.Blocks.`) e pressione
  **Ctrl+Space** para ver as classes da Modelica Standard Library e do pacote do modelo.
- **Mensagens nas linhas**: depois de **Verificar**, cada erro e aviso que o OpenModelica relata é
  marcado na sua linha; passe o mouse para lê-lo. O painel **Mensagens**, abaixo do editor, lista
  todos; clique em um para ir à linha dele.
- **Ctrl+S** (ou **Salvar**) salva o arquivo. Um arquivo também é salvo antes de uma verificação,
  uma simulação, uma exportação ou um diagrama, para que eles sempre usem o que você vê. Se outra
  pessoa salvou o mesmo arquivo nesse meio-tempo, o salvamento é recusado em vez de sobrescrever o
  trabalho dela: copie sua alteração, recarregue e aplique-a de novo.
- **Ctrl+F** busca, **Ctrl+Z** desfaz.

## Arquivos e classes

O pacote de um modelo guarda arquivos Modelica do jeito que toda ferramenta Modelica os guarda:

- `Name.mo` guarda uma classe de nível superior (um modelo, um bloco, um pacote...).
- Um pacote pode ser uma pasta: `Name/package.mo` declara o pacote, `Name/Model.mo` guarda cada
  classe dele (começando com `within Name;`) e `Name/package.order` lista as classes na ordem em
  que são mostradas.

A árvore à esquerda lista os arquivos e, sob cada um, as classes que ele declara. O ▷ verde ao lado
de uma classe que pode ser simulada (um modelo ou bloco que não é `partial`) abre a simulação dela.
**Nova classe** adiciona uma classe em um arquivo próprio e pergunta o que o "New Modelica Class" do
OpenModelica pergunta: o nome, a especialização (model, block, connector, record, function,
package, type, class), uma descrição, uma classe base a estender, o pacote onde colocá-la (um
pacote com pasta própria; a classe é adicionada ao `package.order` dele) e se ela é parcial. Um
modelo ou bloco também pode partir de um modelo pronto (abaixo e em Diagramas).

Limites: 200 arquivos e 8 MB de texto por pacote, 1 MB por arquivo.

## Versões anteriores

Cada salvamento guarda a versão anterior do arquivo; as últimas 50 são guardadas por arquivo.

## O que um modelo não pode usar

O Models roda o OpenModelica no servidor, então um modelo não pode rodar código próprio ali:

- funções `external` (código C ou Fortran) são recusadas, a menos que o administrador as permita;
- `Modelica.Utilities.System`, `Modelica.Utilities.Files` e `Modelica.Utilities.Internal`
  (comandos, arquivos e o ambiente do servidor) são recusados, seja qual for o nome usado.

Uma verificação que encontra um desses diz em que linha ele está, e nada é executado.
