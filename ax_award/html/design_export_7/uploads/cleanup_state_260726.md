# Cleanup state — 2026-07-26

## Final canonical layout

- Repository: `D:\project\unknown-contrastive`
- Detailed record: `D:\project\unknown-contrastive\docs\CLEANUP_MANIFEST_260726.md`
- Physical unknown-image master: `E:\data\images\unknown`
  - 21,143 image files
  - 264,417,178,347 bytes
  - zero-byte files: 0
- `D:\project\unknown-contrastive\data\images` is intentionally empty:
  - direct items: 0
  - files: 0
  - links/reparse points: 0
- The repository has no reparse points or hard-link paths. Do not recreate junctions, symbolic links, or hard links; loaders and manifests must reference `E:\data\images` directly.
- Five junction paths were removed under the final no-links rule:
  - `D:\project\unknown-contrastive\data\images\unknown_train_all`
  - `D:\project\unknown-contrastive\data\images\hf_flowers102`
  - `D:\project\unknown-contrastive\data\images\hf_dtd`
  - `D:\project\unknown-contrastive\data\images\hf_resisc45`
  - `D:\project\unknown-contrastive\runs\fcmae_adapter_residual_scale_screen_260725`
- The four retained E image datasets have zero links/reparse points.
- `D:\project\unknown-contrastive\data` now contains only:
  - `D:\project\unknown-contrastive\data\images`
  - `D:\project\unknown-contrastive\data\pools`
- The earlier statements that D held the physical canonical tree or retained `D:\project\unknown-contrastive\data\raw` and `D:\project\unknown-contrastive\data\positions` are obsolete. Those D paths no longer exist. Position metadata is external under `E:\data\positions`.

## Unknown-master migration evidence

- The former physical duplicate at `D:\project\unknown-contrastive\data\images\unknown_train_all` was permanently deleted: 21,143 files / 264,417,178,347 bytes.
- Before deletion, all 21,143 D relative paths and file sizes matched `E:\data\images\unknown`.
- An evenly distributed 256-file sample totaling 3,204,945,233 bytes had 0 SHA-256 mismatches between D and E.
- The one E-only zero-byte PNG was excluded from every active pool and moved intact to:
  - `E:\unknown-contrastive-archive\data_corrupt_260726\CCH016_00C_08_20260501_010000_67.0_0_PT_ENGINEER.png.zero-byte`
- It is not part of `E:\data\images\unknown`.

## Restored external HF datasets

| Physical path | Classes | Images | Bytes | Per class | Validation |
|---|---:|---:|---:|---:|---|
| `E:\data\images\hf_flowers102` | 102 | 1,020 | 81,224,043 | 10 | all images decoded; zero-byte/non-image/corrupt = 0 |
| `E:\data\images\hf_dtd` | 47 | 1,880 | 212,327,967 | 40 | all images decoded; zero-byte/non-image/corrupt = 0 |
| `E:\data\images\hf_resisc45` | 45 | 1,800 | 45,755,510 | 40 | all images decoded; zero-byte/non-image/corrupt = 0 |

Combined HF restoration: 194 class directories / 4,700 images / 339,307,520 bytes. No D-side compatibility links remain.

## Active pool manifests

Every active unknown-master manifest has `root = E:\data\images\unknown` (slash spelling may differ) and resolves with zero missing files:

| Manifest | Entries | Missing |
|---|---:|---:|
| `D:\project\unknown-contrastive\data\pools\anchor_avg30_repro.json` | 2,260 | 0 |
| `D:\project\unknown-contrastive\data\pools\unknown_eval100.json` | 4,149 | 0 |
| `D:\project\unknown-contrastive\data\pools\unknown_holdout_100_260713.json` | 4,100 | 0 |
| `D:\project\unknown-contrastive\data\pools\unknown_train_normal.json` | 2,998 | 0 |
| `D:\project\unknown-contrastive\data\pools\unknown_train_defectaware_260710.json` | 6,594 | 0 |

The five active unknown-master manifests contain 20,101 entries in total. Two additional active E-rooted manifests also resolve with zero missing files:

- `D:\project\unknown-contrastive\data\pools\mwm38_clean546.json`: `E:\data\images\mixedwm38\rendered\all`, 546 entries
- `D:\project\unknown-contrastive\data\pools\severstal_pilot260726.json`: `E:\data\images\severstal`, 995 entries

Final active loader total: 7 manifests / 21,642 entries / missing 0. Two `*_source_manifest.json` files are historical provenance, not active loader manifests.

### Defect-aware pool provenance

- The historical construction selected every immediate file from 11 named classes. It did not use first-N selection, sorting caps, random sampling, a seed, or recursive selection.
- Current full manifest set check: entries 6,594; unique 6,594; corresponding E class files 6,594; missing 0; extra 0.
- Historical summary/provenance:
  - `D:\project\unknown-contrastive\data\pools\unknown_train_defectaware_260710_source_manifest.json`
  - SHA-256 `7BD2AA017015F811AD5253B8D90A66BFCBE8EAAEF7DE429C01B0213A837D0DBC`
- Active exact-file manifest:
  - `D:\project\unknown-contrastive\data\pools\unknown_train_defectaware_260710.json`
  - SHA-256 `5A8AAF0C64B84BCFB93303F6FE7DAF187167358975E98FC62326FBBFD3FEED3B`
- Keep the source hash for historical provenance and use the full manifest for current input resolution.

## Code and source retention

- `D:\project\unknown-contrastive\scripts\_common.py` now treats `E:\data\images` as the direct-only image root; there is no D fallback.
- Directory-or-manifest selection is centralized through `scripts._common.resolve_pool`; grouping, contrastive, FCMAE fixed-protocol, holdout, hard-42, and scoring entry points use active JSON manifests where physical subsets were deleted.
- Current defaults/examples point to `E:\data\images` or `D:\project\unknown-contrastive\data\pools`; image download default is `E:\data\images\hf_flowers102`.
- Residual-screen consumers use the physical archive at `E:\unknown-contrastive-runs\archives` directly instead of a repository junction.
- Runtime relative project `data\images` defaults and D image fallbacks: 0.
- Link-creation APIs in retained runtime source: 0. Explicit split/export utilities use ordinary copies; active unknown subsets use manifests.
- Active outputs default to `D:\project\unknown-contrastive\runs`; stale result-folder defaults were retired or renamed.
- Fifty-seven obsolete one-off source/launcher/test files were archived before deletion:
  - list: `D:\project\unknown-contrastive\docs\CLEANUP_LEGACY_CODE_ARCHIVE_260726.txt`
  - ZIP: `D:\project\unknown-contrastive\docs\archive\legacy_code_deleted_paths_260726.zip`
  - 58 ZIP entries including the archive manifest; 187,525 bytes
  - SHA-256 `6BC6ED749ADD84B509315D5C32DA6893D07E41D1DC791D7074B98FC6849AC185`
  - remaining listed source files after deletion: 0

## Final link and hard-link cleanup

- A project-wide audit excluding `.git` found 2,780 hard-link paths / 88,752,572 logical bytes.
- Seven `D:\project\unknown-contrastive\runs\clean546\...\clusters` trees were cleaned:
  - 2,277 duplicate hard-linked visualization paths were eliminated.
  - 520 regular cluster files were preserved.
  - final hard-link paths under those trees: 0
- `D:\project\unknown-contrastive\runs\wm811k_fixed_b4\run\abl_wm811k_s42_B4_260724_074724\eval_sparse` was deleted only after all eight `proj_ep*.pt` files matched their same-named peers in `D:\project\unknown-contrastive\runs\wm811k_fixed_b4\run\abl_wm811k_s42_B4_260724_074724\checkpoints` by SHA-256. The checkpoint directory remains.
- Of 62 remaining `cluster_summary` hard-link paths, 39 were converted to verified independent regular files and 23 became regular automatically as sibling links were removed. Temporary conversion files: 0.
- Final counts:
  - repository reparse points: 0
  - repository hard-link paths: 0
  - links/reparse points in the four retained E image datasets: 0

## Verification and preserved evidence

- Focused pytest suite: 33 passed in 20.38 seconds.
- Python compile check passed for the 12 changed/critical Python entry points.
- Final direct-E/no-link compile check passed for 22 affected Python files; eight `--help` smoke checks exited 0.
- `--help` smoke checks passed for pool-manifest creation, SSL training, DDP training, FCMAE fixed protocol, adapter holdout, strict-novel rescore, hard-42 head-only, and May-37 entry points.
- Direct-E loader checks passed; all five active manifests resolve with missing = 0.
- Eight evidence-bearing legacy `outputs_contrastive_*` roots remain.
- Three sweep champion checkpoints and their matching `run_info.json`/logs remain:
  - `D:\project\unknown-contrastive\runs\sweep\abl_sw_t20_B4_260724_102757\checkpoints\proj_ep20.pt`
  - `D:\project\unknown-contrastive\runs\sweep\abl_best_s1_B4_260724_111053\checkpoints\proj_ep18.pt`
  - `D:\project\unknown-contrastive\runs\sweep\abl_best_s2_B4_260724_111604\checkpoints\proj_ep17.pt`
- Previously recorded permanent-delete groups total 291,672 files / 436,042,289,456 logical bytes. The later D physical-master deletion adds 21,143 files / 264,417,178,347 physical bytes and is recorded separately to avoid mixing logical hard-link totals with physical recovery.
