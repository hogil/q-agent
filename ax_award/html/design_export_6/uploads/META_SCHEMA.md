# Meta JSON Schema

각 class 의 사고 시나리오 데이터 구조.

## 위치
`D:/project/failure_agent/meta/<class_name>/meta.json`

## Required fields

| Field | Type | 설명 | 예시 |
|---|---|---|---|
| `class_name` | str | wafer defect class 이름 (snake_case) | "Donut_scratch" |
| `defect_pattern` | str | 결함 패턴 한국어 설명 | "Wafer-scale Donut 패턴 + chip 단위 scratch 결함 동반" |
| `incident_date` | str | 발생 일자 YYYY-MM-DD | "2025-03-14" |
| `fab_line` | str | FAB? -LINE-? | "FAB5-LINE-C" |
| `process_step` | str | 공정 단계 | "CMP (Cu/W/Oxide)" |
| `root_cause` | str | 근본 원인 | "CVD chamber RF coupling 불균일" |
| `suspect_equipment` | str | 혐의 설비 | "AMAT Producer SE (chamber B)" |
| `recipe_issue` | str | recipe 문제 | "RF power asymmetry +3.2%" |
| `yield_impact` | str | yield 손실 | "42% lot yield loss" |
| `corrective_action` | str | 조치 | "Chamber clean + part 교체" |
| `description` | str | 종합 설명 (3-5 문장) | "..." |

## 도메인 매핑 (참고)

### Wafer-scale 패턴 (17 종)

| Pattern | Root cause | Suspect equipment |
|---|---|---|
| Center | Spin coater chuck 변형 / 중심 contamination | TEL CLEAN TRACK ACT 8/12 |
| Donut | CVD/Etch chamber RF coupling 불균일 | AMAT Producer SE / LAM Kiyo |
| Edge-Bottom | Wafer rotation 불균일 + EBR 문제 | ASML NXT:1980Di chuck |
| Edge-Top | 상부 edge handling damage | Hitachi UR-W2810 robot arm |
| Edge-Ring | Edge ring contamination | Edwards iH600 drypump |
| Full | wafer-wide systematic failure | ASML NXT:2050i scanner |
| Thick-Edge | Edge resist 두꺼움 | TEL CLEAN TRACK CLEAN 8/14 |
| BrokenRing | Plasma etch endpoint 실패 | AMAT Centura ETCH |
| CenterCircle | Wafer chuck mark | Vacuum chuck #7 |
| CenterDonut | Center + Donut 복합 | TEL ACT + AMAT Producer |
| CrescentArc | Tilted exposure / handling | ASML NXT:1980Di alignment |
| CrossScratch | Transfer arm 충돌 | Hitachi UR-W2810 A+B |
| DiagonalSmear | Spin coating 회전 불균일 | TEL CLEAN TRACK ACT 8/12 |
| ParallelScratches | CMP pad / cassette 갈림 | AMAT Reflexion CMP Mirra |
| RingDots | Particle contamination (chamber lid) | LAM Kiyo chamber C |
| Row | Probe card row pin 결함 | FormFactor Pyramid #PR-08 |
| Starburst | ESD damage / multi-source | Wafer handling robot R-12 |

### Chip-internal 결함 (5 종)

| Defect | Root cause | Suspect equipment |
|---|---|---|
| bank_boundary | Dicing/saw damage | DISCO DAD3350 dicing saw |
| fork | Litho overlay 오류 | ASML NXT:1980Di overlay |
| invalid_main | Wafer slip line / probe 접촉 불량 | FormFactor probe card |
| scratch | Wafer handling / CMP | Wafer transfer arm |
| scratch_rot | 21° 회전 긁힘 | Brooks BRT-21 robot arm |

### Composite class

`<wafer_pattern>_<chip_defect>` 형식 (예: Donut_scratch, Edge-Bottom_invalid_main):
- root_cause = wafer-level + chip-level 결합
- suspect_equipment = "wafer-level / chip-level"
- recipe_issue = wafer-level + chip-level

## 편집 가이드

### 단일 field 변경
```python
from pathlib import Path
import json
p = Path("D:/project/failure_agent/meta/Donut_scratch/meta.json")
d = json.loads(p.read_text(encoding="utf-8"))
d["suspect_equipment"] = "신규 설비명"
p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
```

### 새 class 추가
1. `D:/project/failure_agent/images/<new_class>/` 폴더 생성 + image 5개 복사
2. `D:/project/failure_agent/meta/<new_class>/meta.json` 작성 (위 schema)
3. `_make_meta.py` 의 `WAFER_DOMAIN` / `CHIP_DOMAIN` dict 에 매핑 추가
4. `python lib/embed_gallery.py` 재실행

### 일괄 합성 (덮어쓰기 주의!)
```bash
python lib/_make_meta.py
```
**경고**: 기존 사용자 편집 모두 덮어쓰기됨. backup 후 실행 권장.

## 검증

```python
import json
from pathlib import Path
META = Path("D:/project/failure_agent/meta")
required = ["class_name", "defect_pattern", "incident_date", "fab_line",
            "process_step", "root_cause", "suspect_equipment", "recipe_issue",
            "yield_impact", "corrective_action", "description"]
issues = []
for cls in sorted(p.name for p in META.iterdir() if p.is_dir()):
    f = META / cls / "meta.json"
    if not f.exists():
        issues.append(f"MISSING: {cls}")
        continue
    d = json.loads(f.read_text(encoding="utf-8"))
    miss = [k for k in required if k not in d]
    if miss:
        issues.append(f"{cls}: missing {miss}")
print("\n".join(issues) if issues else "all 43 meta.json valid ✓")
```
