# Blocos

Os **blocos** são aquilo com que o diagrama de um modelo é desenhado: cada um tem entradas, saídas
e parâmetros. **Blocos**, no menu, os lista por biblioteca. A página de um bloco tem abas, como a de
um bloco no Analytics: **Visão geral** (o que ele faz, suas entradas e saídas), **Código** (o texto
Modelica dele), **Entradas e parâmetros** (uma tabela, para as colunas ficarem alinhadas) e **Usado
por** (os modelos que o colocam).

| Biblioteca | Blocos |
|---|---|
| Fontes | Degrau, rampa, constante, senoide, pulso, uma tabela de valores no tempo |
| Matemática | Ganho, soma, multiplicação, divisão, saturação, limitador de taxa |
| Contínuos | Integrador, derivada, primeira ordem, função de transferência, espaço de estados, tempo morto |
| Controle | PID com anti-windup, liga/desliga |
| Equipamentos de processo | Tanque, bomba, válvula de controle, trocador de calor, CSTR, atraso de medição |
| Sumidouros | Scopes (um ou dois sinais): o que os resultados de uma simulação plotam primeiro |

## Usando um bloco

No editor de um modelo (**Diagrama**, depois **Abrir o editor**), arraste um bloco da paleta para o
diagrama, ou clique em **+ Bloco**, e ligue uma saída a uma entrada. Selecione um bloco para definir
os parâmetros dele no inspetor; **Organizar** dispõe o diagrama da esquerda para a direita.

## Escrevendo blocos

As bibliotecas que acompanham o Models são somente leitura. **Nova biblioteca de blocos** cria um
pacote Modelica vazio do próprio site, com um nome e uma categoria, e o abre no editor de código. As
entradas e saídas reais de um bloco (`RealInput`, `RealOutput`) viram suas portas no diagrama; seus
parâmetros, suas configurações.

Alterar um bloco altera todo modelo que o usa, a partir da próxima simulação dele. As simulações já
feitas mantêm os arquivos com que rodaram.
