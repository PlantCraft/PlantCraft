"""The suite's compute: apps hand tasks to workers that run them away from the apps.

- ``folder``: how a task and its answer travel (a job folder as a tar archive) and the folder a
  worker's gateway shares with each app's executor.
- ``client``: ``ComputeClient``, an app's side (submit, wait, read the answers, cancel).
- ``gateway``: the part of a worker that talks to PlantCraft (no open port, no task code).
- ``executor``: the part that runs an app's tasks (no network, no secret, limits per task).

``python -m plantcraft_sdk.compute gateway|executor`` runs the two parts. docs/compute.md
says how it fits together.
"""
