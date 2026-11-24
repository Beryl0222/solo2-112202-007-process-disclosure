"""要素级许可解析与通用性范围检查。

许可来源（从严并取）：
1. 工程员显式确认（可公开 / 签约可见 / 暂时保密 / 待确认）；
2. 批准登记 approvals（含条件性批准，未验签前不生效）；
3. 默认待确认——资料里没有记录的关系不猜、不用相似词补齐。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .lexicon import GENERIC_FACTORS, SUBSTANTIVE_KINDS
from .models import (
    Approval,
    Clearance,
    Disclosure,
    ElementKind,
    Proposal,
    RefKind,
    Status,
)


@dataclass
class FactorClearance:
    factor: str
    clearance: Clearance
    basis: list[str] = field(default_factory=list)


@dataclass
class GenericOverreach:
    proposal_id: str
    claim: str
    supported_examples: list[str]
    note: str


class ClearanceResolver:
    def __init__(
        self,
        disclosures: list[Disclosure],
        proposals: list[Proposal],
        approvals: list[Approval],
    ) -> None:
        self.disclosures = {d.rid: d for d in disclosures}
        self.proposals = {p.pid: p for p in proposals}
        self.approvals = approvals
        # 工程员显式确认：(proposal_id, factor) -> FactorClearance
        self.overrides: dict[tuple[str, str], FactorClearance] = {}

    # —— 工程员确认 ——
    def set_override(
        self, proposal_id: str, factor: str, clearance: Clearance, actor: str
    ) -> FactorClearance:
        result = FactorClearance(
            factor=factor,
            clearance=clearance,
            basis=[f"{actor} 显式确认：{clearance.value}"],
        )
        self.overrides[(proposal_id, factor)] = result
        return result

    def resolve(self, proposal_id: str, factor: str) -> FactorClearance:
        if (proposal_id, factor) in self.overrides:
            return self.overrides[(proposal_id, factor)]

        bases: list[str] = []
        candidates: list[Clearance] = []
        for approval in self.approvals:
            if approval.proposal_id != proposal_id:
                continue
            # 条件性批准：未验签不生效
            if approval.conditional:
                canonical = self.disclosures.get(approval.canonical_id)
                if canonical is None or not canonical.signed:
                    bases.append(
                        f"{approval.aid} 条件未满足：{approval.condition_note}"
                    )
                    continue
                # 验签后收集同一实施方式链上全部签名页明确公开过的因子
                chain_factors: set[str] = set(canonical.positive_factors)
                for other in self.disclosures.values():
                    if (other.signed
                            and other.impl_group == canonical.impl_group):
                        chain_factors |= other.positive_factors
                if factor in chain_factors:
                    candidates.append(Clearance.PUBLIC)
                    bases.append(
                        f"{approval.aid} 已验签 {approval.canonical_id} 及其同实施方式"
                        "签名页，链上明确公开过此因子"
                    )
                else:
                    bases.append(
                        f"{approval.aid} 虽已验签，但签名链未公开此因子"
                        "（或缺记/否定），不予授权"
                    )
                continue
            if factor in approval.factor_grants:
                granted = approval.factor_grants[factor]
                candidates.append(granted)
                bases.append(f"{approval.aid} 登记：{granted.value}（{approval.scope_text}）")
            else:
                # 批准整体层级覆盖未单列的因子（从严）
                candidates.append(approval.clearance)
                bases.append(
                    f"{approval.aid} 未单列此因子，按整体层级 {approval.clearance.value}"
                )

        if not candidates:
            return FactorClearance(
                factor=factor,
                clearance=Clearance.UNCONFIRMED,
                basis=["无批准记录，留待工程员确认"],
            )
        # 从严并取：最严格的候选生效
        final = max(candidates, key=lambda c: c.rank)
        return FactorClearance(factor=factor, clearance=final, basis=bases)

    def guarded_combos_for(self, proposal_id: str) -> list[list[str]]:
        combos: list[list[str]] = []
        for approval in self.approvals:
            if approval.proposal_id != proposal_id:
                continue
            if approval.conditional:
                continue
            combos.extend(approval.guarded_combos)
        return combos

    # —— 通用性越界 ——
    def check_generic_overreach(self) -> list[GenericOverreach]:
        findings: list[GenericOverreach] = []
        for proposal in self.proposals.values():
            generic = [
                e for e in proposal.elements
                if e.factor in GENERIC_FACTORS and not e.absent
            ]
            if not generic:
                continue
            concrete_objects = sorted({
                e.display for e in proposal.elements
                if e.kind is ElementKind.OBJECT and not e.absent
            })
            # 被引用的他页里的实物，按引用关系追溯（仅限同实施方式且已验签）
            for ref in proposal.references:
                if ref.kind not in (RefKind.SAME_IMPL, RefKind.ANAPHORA):
                    continue
                if ref.status is not Status.VERIFIED:
                    continue
                target = next(
                    (d for d in self.disclosures.values()
                     if d.edition == ref.target), None)
                if target:
                    concrete_objects.extend(
                        e.display for e in target.elements
                        if e.kind is ElementKind.OBJECT and not e.absent
                    )
            unique_objects = sorted(set(concrete_objects))
            if len(unique_objects) <= 1:
                findings.append(GenericOverreach(
                    proposal_id=proposal.pid,
                    claim="、".join(e.span.text for e in generic),
                    supported_examples=unique_objects,
                    note=(
                        "材料自称通用/示范，但可确认公开记录只支持 "
                        f"{unique_objects or '无明确实物'} 这一款实物示例；"
                        "通用性主张超出已公开范围，不得据此外推其他底座/样架"
                    ),
                ))
        return findings

    def substantive_factors(self, proposal: Proposal) -> list[str]:
        """对象/动作/条件中真正参与先例比对的因子。

        “示范”等演示动作是通用性自称的载体，不是工艺原理因子，不参与先例。
        """
        return sorted({
            e.factor for e in proposal.elements
            if e.kind in SUBSTANTIVE_KINDS
            and not e.absent
            and e.factor not in GENERIC_FACTORS
        })
