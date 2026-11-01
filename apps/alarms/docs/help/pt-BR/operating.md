# Operação dos alarmes

**Alarmes** lista todos os alarmes e alertas em uma tabela, os mais urgentes primeiro: alarmes
não reconhecidos, depois alarmes que retornaram ao normal sem reconhecimento, depois os ativos
já reconhecidos, depois os suprimidos. **Precisa de atenção** (o padrão) mantém esses; **Não
reconhecido**, só os que ainda faltam reconhecer; **Todos**, todos os alarmes que as regras
geraram, inclusive os normais. **Só os meus** mantém aqueles pelos quais você ou seus grupos
respondem, e aqueles sobre os quais uma regra notifica você. Filtre por prioridade, estado ou
área acima da tabela, e marque linhas para reconhecê-las juntas.

Uma linha abre o alarme: seu estado, do que ele trata, sua regra e sua ação corretiva, seu valor
com o limite, seu **Histórico** (cada disparo, normalização, reconhecimento, supressão e
alteração) e as **Mensagens enviadas** sobre ele.

Um **alerta** (uma regra pode gerar alertas em vez de alarmes, por exemplo "Execução do
Analytics falhou") também aparece aqui, mas não precisa de reconhecimento e não conta em
Desempenho.

## Estados

| Estado | Significado |
|---|---|
| Não reconhecido | Ativo, e ninguém o reconheceu ainda |
| Reconhecido | Ativo, e um operador já o viu |
| Retornou ao normal, não reconhecido | Voltou ao normal antes que alguém o reconhecesse |
| Suprimido | Não dispara nada até a supressão acabar (uma decisão do operador, com um motivo) |
| Fora de serviço | Não é avaliado (uma decisão de engenharia, ou sua regra está desligada) |
| Normal | Inativo e reconhecido |

Estes são os estados da ISA-18.2.

## Reconhecer

**Reconhecer** diz "eu vi". Um alarme reconhecido continua na lista enquanto estiver ativo.
**Reconhecer todos** reconhece todos os alarmes da lista. A mensagem nas Mensagens do PlantCraft
também tem um botão **Reconhecer**: ele abre o alarme e o reconhece. Quem reconheceu e quando
fica guardado no diário e conta no indicador de tempo até o reconhecimento.

## Suprimir

Suprima um alarme incômodo por um tempo fixo (de 15 minutos a 7 dias) e diga por quê. Enquanto
suprimido, ele continua sendo avaliado, mas não dispara nada. Quando a supressão acaba, ou
alguém a remove, um alarme que ainda está ativo é anunciado de novo e precisa de um novo
reconhecimento.

## A página de um alarme

A página de um alarme mostra seu estado, seu sinal com o limite e cada ocorrência, ou, para um
alarme de um evento repetido, os eventos que contaram e o que o normalizou. **Alterar a regra**
abre a regra de onde ele vem; **Colocar fora de serviço** para só este alarme.

Quem só visualiza vê tudo; reconhecer e suprimir exigem acesso de editor ao Alarms.
