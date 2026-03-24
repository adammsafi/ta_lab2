# CTF vs AMA Feature Selection Report

Generated: 2026-03-24 02:49 UTC  
IC-IR cutoff (CTF): 0.5  

---

## 1. Summary Statistics

### CTF Tier Distribution

| Tier | Count | Pct |
|------|-------|-----|
| active | 7 | 7.3% |
| conditional | 3 | 3.1% |
| watch | 56 | 58.3% |
| archive | 30 | 31.2% |
| **TOTAL** | **96** | 100% |

### AMA (Phase 80) Reference

- Total AMA features ranked: 205
- Best AMA IC-IR: 1.6512
- AMA active rate (cutoff 0.3): 59.0%

---

## 2. Top CTF Features by IC-IR

| # | Feature | IC-IR | IC | Pass Rate | Tier |
|---|---------|-------|----|-----------|------|
| 1 | macd_hist_8_17_9_7d_agreement | 1.2948 | 0.0080 | 100.0% | active |
| 2 | macd_hist_12_26_9_7d_agreement | 1.2948 | 0.0080 | 100.0% | active |
| 3 | macd_12_26_7d_agreement | 1.2948 | 0.0080 | 100.0% | active |
| 4 | macd_8_17_7d_agreement | 1.2948 | 0.0080 | 100.0% | active |
| 5 | close_fracdiff_7d_ref_value | 0.7265 | 0.0438 | 100.0% | active |
| 6 | close_fracdiff_7d_base_value | 0.7265 | 0.0438 | 100.0% | active |
| 7 | sadf_stat_7d_agreement | 0.5170 | 0.0054 | 50.0% | active |
| 8 | bb_width_20_7d_base_value | 0.3612 | 0.0545 | 0.0% | watch |
| 9 | bb_width_20_7d_ref_value | 0.3612 | 0.0545 | 0.0% | watch |
| 10 | bb_width_20_7d_agreement | 0.3308 | 0.0061 | 0.0% | watch |
| 11 | vol_log_roll_20_7d_slope | 0.3208 | 0.0437 | 0.0% | watch |
| 12 | rsi_7_7d_agreement | 0.3101 | 0.0166 | 50.0% | conditional |
| 13 | rsi_21_7d_agreement | 0.3101 | 0.0166 | 50.0% | conditional |
| 14 | rsi_14_7d_agreement | 0.3101 | 0.0166 | 50.0% | conditional |
| 15 | bb_width_20_7d_slope | 0.3043 | 0.0410 | 0.0% | watch |
| 16 | close_fracdiff_7d_agreement | 0.2989 | 0.0059 | 0.0% | watch |
| 17 | vol_parkinson_20_7d_slope | 0.2807 | 0.0352 | 0.0% | watch |
| 18 | ret_arith_7d_base_value | 0.2556 | 0.0114 | 0.0% | watch |
| 19 | ret_log_7d_base_value | 0.2556 | 0.0114 | 0.0% | watch |
| 20 | vol_gk_63_7d_ref_value | 0.2519 | 0.0342 | 0.0% | watch |

---

## 3. Redundancy Analysis

Comparison methodology: Spearman rank correlation between CTF IC-IR values
and their corresponding base indicator IC-IR values from AMA/Phase-80 features.

A high correlation (rho > 0.7) indicates CTF features are redundant with
their base indicators and add little new information.

**Spearman rho (CTF vs base indicator IC-IR):** 0.1923

**Verdict:** LOW redundancy (rho=0.1923)

Interpretation:
- rho > 0.7: CTF features largely replicate base indicator signal
- rho 0.4-0.7: Mixed -- CTF adds some novel signal
- rho < 0.4: CTF features provide substantially different signal

---

## 4. CTF vs AMA Head-to-Head

| Metric | CTF | AMA (Phase 80) |
|--------|-----|----------------|
| Best IC-IR | 1.2948 | 1.6512 |
| Mean IC-IR (all features) | 0.2108 | 0.4754 |
| Active features (cutoff 0.5) | 7 (7.3%) | N/A |

**Head-to-head verdict:** CTF top feature exceeds IC-IR cutoff (0.5) -- adds alpha.

---

## 5. Pruning Recommendations

- Archive tier: 30 features (31.2%)
- Active+Conditional: 10 features retained

**Recommendation:** Include active CTF features in model training pipeline.
Active features show IC-IR >= cutoff and are non-redundant validators.

---

## 6. Data Coverage Note

CTF IC sweep ran on 96 CTF features across available (asset, base_tf) pairs.
Current coverage: 2 assets (BTC id=1, XRP id=1027) at base_tf=1D, ref_tf=7D only.
Full coverage requires running `python -m ta_lab2.scripts.analysis.run_ctf_ic_sweep --all`
after completing a full CTF feature refresh (`python -m ta_lab2.scripts.etl.run_ctf_refresh --all`).
