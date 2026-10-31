within PlantCraftProcess;
model Stream "Material stream with Raoult's law (OMChemSim)"
  extends Simulator.Streams.MaterialStream;
  extends Simulator.Files.ThermodynamicPackages.RaoultsLaw;
end Stream;
