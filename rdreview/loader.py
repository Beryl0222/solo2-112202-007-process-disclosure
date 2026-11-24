"""从 TSV 资料包装载全部记录，并把批准原话解析成许可结构。

只读取资料包，不写回。解析不了的关系不猜，保留原话并置为待确认。
"""
from __future__ import annotations

import sys
from pathlib import Path

from .models import (
    Approval,
    AudienceBatch,
    Clearance,
    Phase,
)
from .parser import parse_disclosure, parse_proposal

# 复用既有资料包的物理格式校验
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pack_check import read_tables  # noqa: E402


# 批准 scope 原话 -> 许可/保密组合的规则映射（受控规则，不做模糊匹配）
SCOPE_RULES: list[dict] = [
    {
        "match": "仅给签约闭门场",
        "clearance": Clearance.SIGNED_ONLY,
        "guarded": [
            ["condition.low_pressure", "action.two_stage_lift"],
            ["condition.low_pressure", "action.hold_contact"],
        ],
        "note": "低压和段间接触合用暂不可公示",
    },
    {
        "match": "公开仅准弹性底座和一般说明",
        "clearance": Clearance.PUBLIC,
        "grants": {
            "object.elastic_base": Clearance.PUBLIC,
            "object.elastic_frame": Clearance.PUBLIC,
            "action.demo": Clearance.PUBLIC,
            "strength.general": Clearance.PUBLIC,
        },
        "note": "公开仅准弹性底座和一般说明，动作不在批准内",
    },
    {
        "match": "验到签名的旧公开页",
        "clearance": Clearance.UNCONFIRMED,
        "conditional": True,
        "note": "需先验到签名公开页，才准采用明确公开过的共同要素",
    },
]


def _parse_approval(row: dict[str, str]) -> Approval:
    scope = row["scope"]
    rule = next((rule for rule in SCOPE_RULES if rule["match"] in scope), None)
    if rule is None:
        # 不认识的批准原话：不猜，整体待确认，原话保留在 scope_text
        return Approval(
            aid=row["id"],
            proposal_id=row["proposal"],
            canonical_id=row["canonical"],
            scope_text=scope,
            clearance=Clearance.UNCONFIRMED,
            condition_note="批准原话未命中受控规则，留待工程员确认",
        )
    return Approval(
        aid=row["id"],
        proposal_id=row["proposal"],
        canonical_id=row["canonical"],
        scope_text=scope,
        clearance=rule["clearance"],
        factor_grants=dict(rule.get("grants", {})),
        guarded_combos=[list(combo) for combo in rule.get("guarded", [])],
        conditional=rule.get("conditional", False),
        condition_note=rule["note"],
    )


def _parse_phase(value: str) -> Phase:
    for phase in Phase:
        if phase.value == value:
            return phase
    return Phase.ONGOING


def load_pack(directory: Path) -> dict:
    """装载并返回全部结构化记录。"""
    tables = read_tables(directory)
    disclosures = [parse_disclosure(row) for row in tables["disclosures.tsv"]]
    proposals = [parse_proposal(row) for row in tables["proposal.tsv"]]
    approvals = [_parse_approval(row) for row in tables["approvals.tsv"]]
    sessions = [
        AudienceBatch(
            sid=row["id"],
            viewers=row["viewers"],
            phase=_parse_phase(row["phase"]),
            seen=[x for x in row["seen"].split("|") if x],
            planned=[x for x in row["planned"].split("|") if x],
        )
        for row in tables["sessions.tsv"]
    ]
    return {
        "disclosures": disclosures,
        "proposals": proposals,
        "approvals": approvals,
        "sessions": sessions,
    }
