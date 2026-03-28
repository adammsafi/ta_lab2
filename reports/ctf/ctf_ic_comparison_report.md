# CTF vs AMA Feature Selection Report

Generated: 2026-03-24 11:52 UTC  
IC-IR cutoff (CTF): 0.5  

---

## 1. Summary Statistics

### CTF Tier Distribution

| Tier | Count | Pct |
|------|-------|-----|
| active | 74 | 12.8% |
| conditional | 59 | 10.2% |
| watch | 242 | 42.0% |
| archive | 201 | 34.9% |
| **TOTAL** | **576** | 100% |

### AMA (Phase 80) Reference

- Total AMA features ranked: 205
- Best AMA IC-IR: 1.6512
- AMA active rate (cutoff 0.3): 59.0%

---

## 2. Top CTF Features by IC-IR

| # | Feature | IC-IR | IC | Pass Rate | Tier |
|---|---------|-------|----|-----------|------|
| 1 | close_fracdiff_90d_agreement | 1.0914 | 0.0282 | 75.0% | active |
| 2 | close_fracdiff_180d_agreement | 1.0914 | 0.0283 | 75.0% | active |
| 3 | close_fracdiff_14d_agreement | 1.0914 | 0.0282 | 75.0% | active |
| 4 | close_fracdiff_30d_agreement | 1.0914 | 0.0282 | 75.0% | active |
| 5 | close_fracdiff_365d_agreement | 1.0914 | 0.0283 | 75.0% | active |
| 6 | close_fracdiff_180d_base_value | 1.0718 | 0.0361 | 100.0% | active |
| 7 | close_fracdiff_365d_ref_value | 1.0718 | 0.0361 | 100.0% | active |
| 8 | close_fracdiff_365d_base_value | 1.0718 | 0.0361 | 100.0% | active |
| 9 | close_fracdiff_180d_ref_value | 1.0718 | 0.0361 | 100.0% | active |
| 10 | close_fracdiff_90d_base_value | 1.0711 | 0.0367 | 100.0% | active |
| 11 | close_fracdiff_90d_ref_value | 1.0711 | 0.0367 | 100.0% | active |
| 12 | close_fracdiff_30d_ref_value | 1.0706 | 0.0369 | 100.0% | active |
| 13 | close_fracdiff_30d_base_value | 1.0706 | 0.0369 | 100.0% | active |
| 14 | close_fracdiff_14d_ref_value | 1.0704 | 0.0371 | 100.0% | active |
| 15 | close_fracdiff_14d_base_value | 1.0704 | 0.0371 | 100.0% | active |
| 16 | close_fracdiff_7d_base_value | 1.0213 | 0.0381 | 100.0% | active |
| 17 | close_fracdiff_7d_ref_value | 1.0213 | 0.0381 | 100.0% | active |
| 18 | close_fracdiff_7d_agreement | 0.9782 | 0.0250 | 64.3% | active |
| 19 | macd_12_26_7d_agreement | 0.8367 | 0.0285 | 100.0% | active |
| 20 | macd_8_17_7d_agreement | 0.8367 | 0.0285 | 100.0% | active |

---

## 3. Redundancy Analysis

Comparison methodology: Spearman rank correlation between CTF IC-IR values
and their corresponding base indicator IC-IR values from AMA/Phase-80 features.

A high correlation (rho > 0.7) indicates CTF features are redundant with
their base indicators and add little new information.

**Spearman rho (CTF vs base indicator IC-IR):** nan

**Verdict:** LOW redundancy (rho=nan)

Interpretation:
- rho > 0.7: CTF features largely replicate base indicator signal
- rho 0.4-0.7: Mixed -- CTF adds some novel signal
- rho < 0.4: CTF features provide substantially different signal

---

## 4. CTF vs AMA Head-to-Head

| Metric | CTF | AMA (Phase 80) |
|--------|-----|----------------|
| Best IC-IR | 1.0914 | 1.6512 |
| Mean IC-IR (all features) | 0.2385 | 0.4754 |
| Active features (cutoff 0.5) | 74 (12.8%) | N/A |

**Head-to-head verdict:** CTF top feature exceeds IC-IR cutoff (0.5) -- adds alpha.

---

## 5. Pruning Recommendations

- Archive tier: 201 features (34.9%)
- Active+Conditional: 133 features retained

**Recommendation:** Include active CTF features in model training pipeline.
Active features show IC-IR >= cutoff and are non-redundant validators.

---

## 6. Data Coverage Note

CTF IC sweep ran on 576 CTF features across available (asset, base_tf) pairs.
Current coverage: 6 asset(s) across ref_tfs: 14d, 180d, 30d, 365d, 7d, 90d.
