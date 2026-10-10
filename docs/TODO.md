# TODO — open items and reminders

Forward-looking work that is intentionally deferred or that needs the owner.
This is the place to record "remember this for later" items so they don't live
only in a session's context.

## Reminders for the owner

1. **Build an NPU autoreporter** to measure `cube_peak` on *real* hardware. The
   sweep results in `docs/reports/07-cube-mmad-peak.md` (and the float MAC rate,
   which is CA-model behaviour until confirmed) were measured on the simulator —
   they are not silicon numbers.

2. **Read up on the build process and how AIC/AIV cores are built and interact.**
   This is background knowledge the owner wanted to acquire; it is not yet a task
   with a concrete deliverable.

## Deferred task: 950 vs 910 characteristics

The owner observed "950 is not as good as 910" and asked to gather both
generations' characteristics (bandwidth, cache sizes, arithmetic capabilities)
into a detailed comparison picture. Deferred ("not right now, just remember it").

Source material already located:
- `vendor-src/asc-devkit/docs/zh/guide/programming_guide/advanced_programming/hardware_implementation/architecture_spec/npu_arch_2201.md`
- `vendor-src/asc-devkit/docs/zh/guide/programming_guide/advanced_programming/hardware_implementation/architecture_spec/npu_arch_3510.md`
  (also `npu_arch_2002.md`, `npu_arch_3002.md`, and `hardware_constraints/npu_arch_2201.md`)
- Simulator config (container): `tools/simulator/dav_{2201,3510}/lib/config.json`,
  `config_stars.json` (core counts), `config_hwts.json` (2201 only);
  `x86_64-linux/simulator/dav_2201/conf/release_config.json`;
  `x86_64-linux/simulator/dav_3510/camodel/camodel_v100.json`.
- 3510 CA-model hardware-block libs (container, `x86_64-linux/simulator/dav_3510/camodel/`,
  ~40 `.so` files: `libHBMSim`, `libL2Buf`, `libDDR_Inf`, `libSDMAA`, `libSDMAM`,
  `libSLLC`, `libUB`, `libCuberWrapper`, `libMATA`, `libPowerModel`, `libSoC`,
  `libpem_davinci`, `libChiRingFabric`, …). The 3510 simulator is a finer-grained
  block-level ESL model than 2201.

Already-extracted summaries that feed this: `docs/REFERENCE.md` (buffer sizes /
K0 / measured rates), `docs/reports/07-cube-mmad-peak.md` (measured FLOPS).
