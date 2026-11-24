"""研发编审工具：判断演示中哪些原理确实共同公开过、哪些组合会泄露研发方案。

数据来源是业务资料包中的 TSV（旧展示物 disclosures、拟演示稿 proposal、
批准 approvals、观众场次 sessions）。本包只做语义分析与留痕，不修改资料包。
"""
from __future__ import annotations

__version__ = "1.0.0"
