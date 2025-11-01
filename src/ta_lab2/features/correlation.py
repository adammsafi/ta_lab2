from __future__ import annotations
import numpy as np
import pandas as pd

def acf(x: pd.Series, nlags: int = 40, demean: bool = True) -> pd.Series:
    s = pd.Series(x).dropna().astype(float)
    if len(s) == 0:
        return pd.Series([np.nan]*(nlags+1), index=range(nlags+1), name="acf")
    if demean:
        s = s - s.mean()
    var = (s**2).sum()
    ac = [1.0]
    for k in range(1, nlags + 1):
        cov = (s.iloc[k:] * s.iloc[:-k]).sum()
        ac.append(float(cov / var) if var != 0 else np.nan)
    return pd.Series(ac, index=range(0, nlags + 1), name="acf")

def pacf_yw(x: pd.Series, nlags: int = 20) -> pd.Series:
    s = pd.Series(x).dropna().astype(float)
    if len(s) == 0:
        return pd.Series([np.nan]*(nlags+1), index=range(nlags+1), name="pacf")
    s = s - s.mean()
    # autocov sequence
    gamma = np.array([
        (s[:len(s)-k] @ s[k:]) / len(s) if k > 0 else (s @ s) / len(s)
        for k in range(0, nlags+1)
    ])
    pac = np.zeros(nlags+1)
    pac[0] = 1.0
    phi = np.zeros((nlags+1, nlags+1))
    var = gamma[0]
    for k in range(1, nlags+1):
        num = gamma[k] - np.sum(phi[k-1,1:k] * gamma[1:k][::-1])
        den = var - np.sum(phi[k-1,1:k] * gamma[1:k])
        phi[k,k] = num / den if den != 0 else np.nan
        for j in range(1, k):
            phi[k,j] = phi[k-1,j] - phi[k,k]*phi[k-1,k-j]
        pac[k] = phi[k,k]
    return pd.Series(pac, index=range(0, nlags+1), name="pacf")

def rolling_autocorr(s: pd.Series, lag: int = 1, window: int = 100) -> pd.Series:
    return s.rolling(window).corr(s.shift(lag)).rename(f"roll_ac_{lag}_{window}")

def xcorr(a: pd.Series, b: pd.Series, max_lag: int = 20, demean: bool = True) -> pd.Series:
    A = pd.Series(a).astype(float)
    B = pd.Series(b).astype(float)
    A, B = A.align(B, join="inner")
    if len(A) == 0:
        return pd.Series([np.nan]*(2*max_lag+1), index=range(-max_lag, max_lag+1), name="xcorr")
    if demean:
        A, B = A - A.mean(), B - B.mean()
    var = np.sqrt((A**2).sum() * (B**2).sum())
    vals = []
    lags = range(-max_lag, max_lag + 1)
    for k in lags:
        if k < 0:
            cov = (A[:k] * B[-k:]).sum()
        elif k > 0:
            cov = (A[k:] * B[:-k]).sum()
        else:
            cov = (A * B).sum()
        vals.append(float(cov / var) if var != 0 else np.nan)
    return pd.Series(vals, index=list(lags), name="xcorr")
