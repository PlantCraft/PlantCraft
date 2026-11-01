within PlantCraftProcess;
model FlashDrum "Flash drum with Raoult's law (OMChemSim): vapour leaves by Out1, liquid by Out2"
  extends Simulator.UnitOperations.Flash;
  extends Simulator.Files.ThermodynamicPackages.RaoultsLaw;
end FlashDrum;
