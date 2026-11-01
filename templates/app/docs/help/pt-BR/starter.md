# StarterCraft

O StarterCraft guarda uma nota sobre qualquer ativo da planta: uma leitura feita em campo, um
lembrete para o próximo turno, o que foi mudado em uma malha e por quê.

## Notas

**Notas** lista todas as notas, das mais novas para as mais antigas, com o ativo de cada uma.
Digite no filtro para reduzir a lista, ou abra as notas de um ativo pelo link dele.

- **Nova nota**: escolha o ativo na árvore de ativos do PlantCraft e escreva o texto (até 4.000
  caracteres). Pessoas com papel de Engenharia e administradores escrevem notas; quem tem
  papel de Leitura, lê.
- **Excluir** uma nota pela página dela. Toda mudança fica registrada no log de auditoria do
  PlantCraft, com quem fez e quando.

Uma nota aponta para o ativo; ela não o copia. Quando o ativo é renomeado no PlantCraft, a nota
mostra o novo nome. Quando o ativo é removido, a nota continua e mostra o id do ativo.

## Crie o seu próprio app

O StarterCraft é o modelo dos apps da suíte: copie, dê um nome (`make rename NAME=Logbook`) e
siga o `docs/quickstart.md` dele.
