#!/usr/bin/env python3
"""Small statistics helpers for comparing groups of runs. Standard library only."""

import math
from statistics import NormalDist, mean, stdev

# Two-sided 95% Student-t critical values, df = 1..30.
_T95 = [
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
]


def t_critical_95(df):
    if df < 1:
        return float("nan")
    if df <= len(_T95):
        return _T95[df - 1]
    if df <= 60:
        return 2.000
    if df <= 120:
        return 1.980
    return 1.960


def mean_ci95(values):
    """Return (mean, sd, half_width) of a 95% t confidence interval for the mean."""
    n = len(values)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    m = mean(values)
    if n < 2:
        return m, float("nan"), float("nan")
    sd = stdev(values)
    return m, sd, t_critical_95(n - 1) * sd / math.sqrt(n)


def percentile(values, q):
    """Linear-interpolated percentile, q in [0, 100] (same as numpy's default)."""
    if not values:
        return float("nan")
    s = sorted(values)
    pos = (len(s) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    tie_sizes = []
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        if j > i:
            tie_sizes.append(j - i + 1)
        i = j + 1
    return ranks, tie_sizes


def _u_distribution(n1, n2):
    """Exact null distribution of U as counts per U value (no ties)."""
    # dp[j][u] = number of arrangements of i x-values and j y-values giving U = u
    prev = [[1] for _ in range(n2 + 1)]
    for i in range(1, n1 + 1):
        cur = [[1]]
        for j in range(1, n2 + 1):
            a = cur[j - 1]
            b = prev[j]
            size = i * j + 1
            row = [0] * size
            for u, c in enumerate(a):
                row[u] += c
            for u, c in enumerate(b):
                if u + j < size:
                    row[u + j] += c
            cur.append(row)
        prev = cur
    return prev[n2]


def mann_whitney_u(x, y):
    """Two-sided Mann-Whitney U test.

    Returns dict(u, p, method). Uses the exact distribution when there are no ties
    and both groups have at most 20 samples; otherwise the normal approximation with
    tie and continuity correction (matches scipy.stats.mannwhitneyu defaults).
    """
    n1, n2 = len(x), len(y)
    if n1 == 0 or n2 == 0:
        return {"u": float("nan"), "p": float("nan"), "method": "n/a"}

    ranks, ties = _ranks(list(x) + list(y))
    r1 = sum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1

    if not ties and n1 <= 20 and n2 <= 20:
        dist = _u_distribution(n1, n2)
        total = float(sum(dist))
        u_big = int(round(max(u1, u2)))
        p_upper = sum(dist[u_big:]) / total
        return {"u": u1, "p": min(1.0, 2.0 * p_upper), "method": "exact"}

    n = n1 + n2
    mu = n1 * n2 / 2.0
    tie_term = sum(t ** 3 - t for t in ties)
    sigma = math.sqrt(n1 * n2 / 12.0 * ((n + 1) - tie_term / (n * (n - 1))))
    if sigma == 0:
        return {"u": u1, "p": 1.0, "method": "normal"}
    z = (max(u1, u2) - mu - 0.5) / sigma
    p = 2.0 * (1.0 - NormalDist().cdf(z))
    return {"u": u1, "p": min(1.0, max(0.0, p)), "method": "normal"}


def cliffs_delta(x, y):
    """Cliff's delta: P(x > y) - P(x < y). Range [-1, 1]."""
    if not x or not y:
        return float("nan")
    gt = lt = 0
    for a in x:
        for b in y:
            if a > b:
                gt += 1
            elif a < b:
                lt += 1
    return (gt - lt) / (len(x) * len(y))


def cliffs_magnitude(d):
    """Romano et al. (2006) thresholds."""
    if d != d:
        return "n/a"
    a = abs(d)
    if a < 0.147:
        return "negligible"
    if a < 0.33:
        return "small"
    if a < 0.474:
        return "medium"
    return "large"
