# Architecture

## Target matrix

| Product | Compiler architecture | Vector programming | Matrix programming |
|---|---|---|---|
| Ascend 910B / Atlas A2 | `dav-2201` | MemBase UB `AscendC::Add` | direct `LoadData` + `Mmad` + `Fixpipe` |
| Ascend 950PR/DT | `dav-3510` | RegBase `RegTensor` + `Reg::Add` | direct `LoadData` + `Mmad` + `Fixpipe` |

No executable uses `AscendC::Matmul`, `IterateAll`, or `REGIST_MATMUL_OBJ`.

## Data paths

Standalone add:

```text
GM -> UB -> vector add -> UB -> GM
```

On `dav-3510`, the vector operation explicitly loads UB into `RegTensor`, adds
registers, and stores them to UB. `dav-2201` has no public general-purpose
RegTensor API, so its lowest supported equivalent is the MemBase UB basic API.

Direct MMAD:

```text
A/B GM ND -> L1 NZ -> L0A/L0B -> MMAD -> L0C NZ -> Fixpipe -> C GM ND
```

The architecture branches differ deliberately. `dav-2201` uses L0A ZZ and
`LoadData2DParams`; `dav-3510` uses L0A NZ and `LoadData2DParamsV2`. Both use
L0B ZN, float accumulation, and half output.

Fused add-MMAD-add:

```text
one __mix__(1, 2) launch
  AIV0/AIV1: A0 + A1 -> staged A in GM
  mode-2 cross-core synchronization
  AIC: staged A x B -> staged C in GM
  mode-2 cross-core synchronization
  AIV0/AIV1: staged C + addend -> output
```

The GM staging is intentional. It provides a supported visibility boundary
between MemBase/RegBase Vector execution and Cube execution on both target
generations while preserving a single fused kernel launch.

## Synchronization invariants

`__mix__(1, 2)` launches one AIC and two AIVs per logical block. AIC block `i`
maps to AIV blocks `2*i` and `2*i+1`. Both AIVs call the AIV-to-AIC flag before
the corresponding AIC proceeds. The AIC calls the AIC-to-AIV flag only after
Fixpipe has made its result visible. All participating cores execute exactly
one matching operation for each flag, avoiding unmatched-counter timeouts.

Cross-core synchronization is not inherently fragile. It is sensitive to
incorrect group ratios, block indexing, flag pairing, flag-ID collisions, and
pipeline selection. This project fixes those choices to the documented mode-2
pattern and uses no advanced Matmul object that could reserve overlapping IDs.
