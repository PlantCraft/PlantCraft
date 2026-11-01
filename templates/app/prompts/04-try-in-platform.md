# 04: Try it inside PlantCraft

```text
Run the app inside a local PlantCraft and check it as a person would.

1. If PlantCraft is not installed in this Python, from the PlantCraft checkout:
   python3 -m pip install -e sdk/python -e ".[server,opcua]" && python3 -m pip install -e simulator
2. In this folder: `make dev` (the Simulator, PlantCraft on http://127.0.0.1:8060 and the app on
   its port, with an app key and listed in PlantCraft's launcher). Wait for both to answer.
3. With Playwright: open PlantCraft, open the app from the launcher, do the main task of the app
   end to end (create, open, change, delete), switch to a viewer from the profile
   menu and check they cannot write. Take a screenshot of each page.
4. Tell me what worked, what did not, and fix what is wrong in the app (never in PlantCraft).
```
