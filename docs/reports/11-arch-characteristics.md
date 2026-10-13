# 11 — Ascend 950 (dav-3510) vs 910B (dav-2201) hardware characteristics

## What we did

Consolidated everything we know about the two chips into one place: the vendor
architecture-spec docs (`npu_arch_2201.md` / `npu_arch_3510.md`), the PTO cost
model we extracted (`vendor-src/pto/`), our own simulator measurements, and the
UB bank structure from report 09. Then drew it up as a set of diagrams — one big
overview plus focused views per hardware component.

## Why we did it

The deferred task "950 vs 910 characteristics" had been sitting in `docs/TODO.md`
since the early sessions. Every experiment so far (banks, cube peak, SIMT, PTO)
has produced a fragment of this picture, but nothing assembled the fragments
side by side. A set of diagrams makes the *differences* between the two
generations immediately visible.

## What we wanted to check

For each generation: memory hierarchy sizes + bandwidth, the compute units
(cube / vector / scalar), the data paths between buffers, the UB bank structure,
and the SIMT block (950 only) — all with the actual numbers, so a reader can
compare 910B and 950 without re-reading five reports.

## The big picture

```mermaid
flowchart LR
    subgraph HBM["Global Memory (HBM)"]
        GM["HBM / DDR<br/>card-level"]
    end

    subgraph D2201["Ascend 910B · dav-2201 (Atlas A2/A3)"]
        direction TB
        L1A["L1 Unified Buffer<br/>512 KB (523776 B)"]
        subgraph C2201["per-core pair (24 AIC : 48 AIV)"]
            direction LR
            subgraph AIC1["AIC — Cube"]
                L0A1["L0A 64 KB"]
                L0B1["L0B 64 KB"]
                MMAD1["Cube (MMAD)<br/>4096 MAC/cyc half<br/>1024 MAC/cyc fp32"]
                L0C1["L0C 128 KB"]
                BT1["BiasTable 1 KB"]
            end
            subgraph AIV1["AIV — Vector"]
                UB1["UB 192 KB (196352 B)"]
                VEC1["Vector (MemBase)<br/>memory-to-memory VADD"]
                SC1["Scalar"]
            end
        end
    end

    subgraph D3510["Ascend 950 · dav-3510 (950PR / 950DT)"]
        direction TB
        L1B["L1 Unified Buffer<br/>512 KB (524288 B)"]
        subgraph C3510["per-core pair (AIC : AIV = 1 : 2)"]
            direction LR
            subgraph AIC2["AIC — Cube"]
                L0A2["L0A 64 KB"]
                L0B2["L0B 64 KB"]
                MMAD2["Cube (MMAD)<br/>4096 MAC/cyc half<br/>+ FP8 / HiF8"]
                L0C2["L0C 256 KB"]
                BT2["BiasTable 4 KB"]
            end
            subgraph AIV2["AIV — Vector"]
                UB2["UB 256 KB (253952 B)"]
                VEC2["Vector (RegBase)<br/>+ SIMT"]
                SC2["Scalar (+FP64)"]
            end
        end
    end

    GM --> L1A
    GM --> L1B
    L1A --> AIC1
    L1A --> AIV1
    L1B --> AIC2
    L1B --> AIV2
```

## Buffers, side by side

| buffer | dav-2201 (910B) | dav-3510 (950) | change |
|---|---|---|---|
| UB | 192 KB (196352 B) | 256 KB (253952 B) | +33 % |
| L1 | 512 KB (523776 B) | 512 KB (524288 B) | — |
| L0A | 64 KB | 64 KB | — |
| L0B | 64 KB | 64 KB | — |
| L0C | 128 KB | 256 KB | **×2** |
| BiasTable | 1 KB | 4 KB | ×4 |
| Fixpipe | 2 KB | 4 KB | ×2 |

Notes: 2201 reserves 256 B in both UB and L1; 3510 UB = 248 KB + VF stack
(~6 KB) + reserve (~2 KB), and shrinks by 32–128 KB when SIMD+SIMT DCache share
UB (down to ~224 KB usable).

## Memory bandwidth

2201 per-pipe bandwidth from the PTO cost model (`arch_config.hpp`,
`kA2A3ArchConfig`, frequency 1.85 GHz — the values are the model's GiB/s):

```mermaid
flowchart TB
    GM["Global Memory (HBM)"]
    L1["L1 (Unified Buffer) 512 KB"]
    UB["UB 192 KB"]
    L0A["L0A 64 KB"]
    L0B["L0B 64 KB"]
    L0C["L0C 128 KB"]
    BT["BiasTable 1 KB"]

    GM -->|"GM→UB 100.9 GiB/s"| UB
    GM -->|"GM→L1 135.0 GiB/s"| L1
    UB -->|"UB→GM 188.5 GiB/s"| GM
    L1 -->|"L1→GM 32 GiB/s"| GM
    UB -->|"UB→UB 1024 GiB/s"| UB
    L0C -->|"L0C→GM 70 GiB/s"| GM
    L0C -->|"L0C→L1 128 GiB/s"| L1
    L1 -->|"L1→L0A 441 GiB/s"| L0A
    L1 -->|"L1→L0B 220.5 GiB/s"| L0B
    L1 -->|"L1→BT 32 GiB/s"| BT
```

The `L1→L0A : L1→L0B` ratio is exactly **2 : 1** (441 : 220.5), matching the
arch-spec 256 : 128 B/cycle. The two generations' *data paths* (per the arch
spec, B/cycle):

```mermaid
flowchart LR
    subgraph P2201["dav-2201 — 2 data paths"]
        direction TB
        p1["L1 → L0A : 256 B/cyc"]
        p2["L1 → L0B : 128 B/cyc"]
    end
    subgraph P3510["dav-3510 — 6 data paths"]
        direction TB
        q1["L1 → L0A : 256 B/cyc"]
        q2["L1 → L0B : 256 B/cyc  (B path doubled)"]
        q3["L1 → UB : 128 B/cyc  (new)"]
        q4["UB → L1 : 128 B/cyc  (new)"]
        q5["L0C → UB : 128 B/cyc  (new)"]
        q6["L0C → L1 : 128 B/cyc  (new)"]
    end
```

950 keeps the cube feed paths and adds four new ones: `UB↔L1` and `L0C→UB`,
and drops the old `GM→L0A/B` direct feeds — everything flows through L1.

## Vector unit: MemBase → RegBase

```mermaid
flowchart LR
    subgraph V2201["dav-2201 — MemBase"]
        direction TB
        m1["operands are UB byte addresses<br/>VADD XD / XN / XM"]
        m2["one memory-to-memory op<br/>does the whole block"]
        m3["32 B aligned · no register programming"]
        m4["mask = special mask register"]
    end
    subgraph V3510["dav-3510 — RegBase"]
        direction TB
        r1["operands are registers<br/>RV_VADD Vd / Vn / Vm + Pg"]
        r2["VLD / VST move UB ↔ registers"]
        r3["256 B per beat"]
        r4["mask = MaskReg"]
        r5["reg file: 256B×32 vec · 32B×8 mask<br/>4B×8 addr · 32B×4×2 unalign"]
    end
```

The architectural register file is 32 × 256 B vector registers (the PTO
`uarch.csv` says `vreg_num=68`, i.e. 68 *physical* registers with renaming).

## UB bank structure (from report 09)

```mermaid
flowchart LR
    subgraph B2201["dav-2201 UB — 48 banks = 3 regions × 16 groups"]
        direction TB
        b1["region = addr[17:16] (0,1,2)<br/>which 64-KB block"]
        b2["group = addr[8:5] (16 values)<br/>the conflict axis"]
        b3["bank_id = region·16 + group"]
        b4["group period 512 B · bank 4 KB"]
        b5["1 read + 1 write port per group"]
    end
    subgraph B3510["dav-3510 UB — 16 banks = 2 banks × 8 groups"]
        direction TB
        c1["low-bit interleave"]
        c2["bank = addr[8] (2) · group = addr[7:5] (8)"]
        c3["group period 256 B · bank 16 KB"]
        c4["4 sub-banks × 8 B (gather / scatter)"]
        c5["2 read + 1 write port per group"]
    end
```

Both generations read **16 rows = 512 B per beat** across their bank groups;
950 gets there with 8 groups × 2 banks, 910B with 16 groups × 1 bank.

## Cube unit

```mermaid
flowchart TB
    subgraph C2201["dav-2201 — MMAD"]
        f["cycles = 6 + cpr × (mTiles × kTiles × nTiles)<br/>mTiles=⌈m/16⌉ · kTiles=⌈k/(32/sizeof(T))⌉ · nTiles=⌈n/16⌉"]
        f --> h["fp16 / bf16: cpr = 1<br/>1 cyc / 16×16×16 = 4096 MAC/cyc"]
        f --> fl["fp32: cpr = 2<br/>2 cyc / 16×16×8 = 1024 MAC/cyc"]
    end
    subgraph C3510["dav-3510 — MMAD"]
        d["dtypes: FP32/FP16/BF16/HiF8/FP8_E4M3/FP8_E5M2/U8/S8"]
        d2["1 beat = 16×16×16 fp16 · 16×32×32 int8"]
        d3["half/bf16: 4096 MAC/cyc"]
        d4["fp32: 256 MAC/cyc (CA-model; verify on silicon)"]
    end
```

Measured cube peak (CA-model sim, ~1.8 GHz):

| dtype | 910B | 950 | ideal ratio |
|---|---|---|---|
| half / bf16 | 4096 MAC/cyc (14.7 TFLOPS) | 4096 MAC/cyc (14.7 TFLOPS) | 1.00 |
| int8 | 8192 (29.5 TOPS) | 8192 (29.5 TOPS) | 1.00 |
| float | 1024 MAC/cyc (3.68 TFLOPS) | 256 MAC/cyc (0.92 TFLOPS) | 2.0 / 8.0 |

## SIMT (950 only)

```mermaid
flowchart TB
    subgraph SIMT["AIV SIMT block (dav-3510)"]
        ws["4 warp schedulers per AIV"]
        rf["SIMT register file 128 KB"]
        dc["SIMT DCache up to 128 KB<br/>reuses UB as cacheline (128 B granularity)"]
    end
    ws --> rf
```

Thread → register mapping (SIMT register file is 128 KB total):

| threads per block | registers per thread |
|---|---|
| 1 – 256 | 127 |
| 257 – 512 | 64 |
| 513 – 1024 | 32 |
| 1025 – 2048 | 16 |

## Vector-instruction timing (950, from `isa.csv`)

| op | latency | throughput |
|---|---|---|
| VADD / VSUB / VMUL (fp32) | 7 | 2 |
| VMAX / VMIN (fp32) | 6 | 2 |
| VADDS / VMULS (scalar) | 7 | 1 |
| VLDS (load) / VSTS (store) | 9 | 1 |
| VEXP (fp32) | 16 | 4 |
| VDIV (fp32) | 17 | 4 |
| VCADD (fp32) | 22 | 1 |

`uarch.csv` (950): issue ports 2, load ports 2, store ports 1, IDU issue width
5, IDU window 6, SHQ depth 58, EXQ depth 26. Vector-instruction queue depth
(AIC/AIV) is 0/64 on 910B vs 0/32 on 950.

## Inter-core communication & sync

- 910B: inter-core data goes through **Global Memory**.
- 950: inter-core data via **SSBuffer**; adds a 1:1 AIC:AIV sync mode (mode 4).

## Reproduce

```bash
# The arch-spec docs and the PTO cost model are the sources (vendor-src/ is
# gitignored; re-copy PTO with the docker-run one-liner from report 10).
# Arch specs:
#   vendor-src/asc-devkit/docs/zh/guide/programming_guide/advanced_programming/
#     hardware_implementation/architecture_spec/npu_arch_{2201,3510}.md
# 2201 bandwidth table (GiB/s, kA2A3ArchConfig):
#   vendor-src/pto/costmodel/arch_config.hpp
# 950 vector timing:
#   vendor-src/pto/costmodel/a5/VfSim/params/isa.csv      # VADD,f32,6,7,2,5,...
#   vendor-src/pto/costmodel/a5/VfSim/params/uarch.csv    # issue_ports=2,...
# 2201 cube formula (fp16=1 cyc/repeat, fp32=2 cyc):
#   vendor-src/pto/costmodel/a2a3/formula_costmodel/formula_backend_compute.hpp

# Measured cube peak (reproduces the "measured" table):
./scripts/docker-run.sh ./scripts/build.sh sim dav-2201
./scripts/docker-run.sh ./scripts/build.sh sim dav-3510
./scripts/docker-run.sh python3 scripts/cube_sweep.py --arch 2201
#   half 4096 MAC/cyc, float 1024 MAC/cyc ...
```

Mermaid renders these diagrams in any GitHub/VS Code markdown preview.
