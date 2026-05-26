# htsim Topology Notes

This directory stores the 3 topology files used by the 10 routing/scheduling algorithms.

## Topology File Format

The first line is:

`H dl ul ntor N`

- `H`: hosts
- `dl`: downlinks per host (metadata)
- `ul`: uplinks per host (metadata)
- `ntor`: number of ToR in header (metadata)
- `N`: total graph nodes in adjacency matrix

Then follows an `N x N` 0/1 adjacency matrix.

## 3 Topologies

- `n80_k8_c8_eps0.txt`
  - 80 ToR + 0 EPS
  - pure OCS-style core
- `n80_k7_c8_eps1.txt`
  - 80 ToR + 1 EPS
  - hybrid OCS+EPS core
- `n80_k0_c8_eps8.txt`
  - 80 ToR + 8 EPS
  - EPS-rich core

## Algorithm -> Topology Mapping

From the existing baseline runner (`ocs-eps/flow_level_sim_project_inference/run.sh`):

- Use `n80_k8_c8_eps0.txt`:
  - `pure_ocs_ksp`
  - `pure_ocs_ksp_greedy`
  - `pure_ocs_pruned`

- Use `n80_k7_c8_eps1.txt`:
  - `ocs_eps_pruned` (`strict_queue_greedy` alias)
  - `ocs_eps_large_small`
  - `ocs_eps_global_ksp`
  - `ocs_eps_preset_greedy`
  - `ocs_eps_preset_dynamic_greedy`

- Use `n80_k0_c8_eps8.txt`:
  - `eps_ecmp`
