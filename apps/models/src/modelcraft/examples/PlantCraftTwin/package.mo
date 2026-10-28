within;
package PlantCraftTwin "Models of the PlantCraft simulated plant, exported as FMUs for TwinCraft"
  annotation(
    version = "0.1.0",
    Documentation(info = "<html><p>Process models of PlantCraft's control loops: each loop's process is a first order plus dead time response of its measured variable to the valve position, with an optional measured disturbance. TwinCraft runs them as FMI 2.0 co-simulation FMUs beside the plant and compares their prediction with what the plant measures.</p></html>"));
end PlantCraftTwin;
