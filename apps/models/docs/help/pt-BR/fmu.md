# Exportando FMUs

Uma FMU (Functional Mock-up Unit) é um modelo empacotado como um arquivo padrão (FMI, a Functional
Mock-up Interface) que outras ferramentas podem executar: o PlantCraft Analytics e a maioria das
ferramentas de simulação.

**Exportar FMU** (o botão de pacote na página de um modelo, ou na barra de ferramentas do editor de
código) gera uma a partir do modelo:

| Escolha | Significado |
|---|---|
| Versão FMI | 2.0 (lida pela maioria das ferramentas) ou 3.0 |
| Tipo | **Cossimulação**: a FMU leva seu próprio solver (CVODE) e avança sozinha; é o que o PlantCraft Analytics executa. **Model exchange**: a ferramenta que a executa traz o solver. **Ambos** |

A FMU é gerada para Linux (64 bits), com as bibliotecas dentro, então roda sem o OpenModelica. A
exportação roda na fila: a página dela mostra a versão FMI, a plataforma, as entradas, as saídas e
o número de parâmetros, e **Baixar a FMU**.

## Usando em outro lugar

Clique em **Baixar a FMU** e use-a em qualquer ferramenta que execute FMUs. As exportações são listadas em
**Simulações › Fila**, com todas as simulações.

O Models não envia FMUs ao Analytics: os modelos são para estudo e nunca rodam na planta. Um modelo
destinado a uma ferramenta que o executa contra a planta tem entradas de nível superior (o que a
planta lhe dá: vazões, aberturas, setpoints) e saídas (o que ele prevê: níveis, temperaturas). Os
exemplos **Analytics models** guardam os modelos que acompanham o Analytics para as malhas do
Simulator.
