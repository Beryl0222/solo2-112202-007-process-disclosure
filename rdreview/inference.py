"""按观众视角的联合推断、泄密路径与编审改法。

核心立场：观众看不到“稿件边界”，他们把展板、讲解、会后资料当成一套材料。
只要同一批观众接触的材料里，保密组合的各因子都能找到，且存在把材料串起来
的线索（同场指代、图注、共同对象、动作顺序），该组合即视为可联合推出——
哪怕保密词本身已被删掉。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .clearance import ClearanceResolver
from .lexicon import FACTOR_DISPLAY, SUBSTANTIVE_KINDS
from .models import (
    AudienceBatch,
    BundleVerdict,
    Clearance,
    EditOption,
    ElementKind,
    LeakPath,
    Proposal,
    RefKind,
    SplitTrap,
)

# 讲清原理所需的前提：删掉某因子后，依赖它的原理动作就失去前提。
PREMISES: dict[str, list[str]] = {
    "action.two_stage_lift": ["object.elastic_base"],
    "action.hold_contact": ["action.two_stage_lift"],
    "condition.low_pressure": [],
    "action.one_step": ["object.base"],
}


@dataclass
class ViewItem:
    proposal: Proposal
    factors: set[str]
    caption_factors: set[str]
    cues: list[str]
    evidence: list[str]


class InferenceEngine:
    def __init__(
        self,
        proposals: list[Proposal],
        resolver: ClearanceResolver,
        disclosures: list,
    ) -> None:
        self.proposals = {p.pid: p for p in proposals}
        self.resolver = resolver
        self.disclosures = disclosures
        # 工程员登记的替换词：pid -> {原因子: (替换因子, 说明)}
        self.replacements: dict[str, dict[str, tuple[str, str]]] = {}
        # 工程员登记的改观众：pid -> 目标观众批次
        self.re_audience: dict[str, str] = {}
        # 编审删改（模拟）：pid -> 被删因子
        self.dropped: dict[str, set[str]] = {}

    @staticmethod
    def _batch_is_signed(batch: AudienceBatch) -> bool:
        """签约/闭门观众批次：名称含“签约”或“闭门”。"""
        return "签约" in batch.viewers or "闭门" in batch.viewers

    # ------------------------------------------------------------------
    # 观众视图
    # ------------------------------------------------------------------
    def _view_item(self, pid: str) -> ViewItem:
        proposal = self.proposals[pid]
        dropped = self.dropped.get(pid, set())
        factors: set[str] = set()
        caption_factors: set[str] = set()
        evidence: list[str] = []
        for element in proposal.elements:
            if element.absent or element.kind not in SUBSTANTIVE_KINDS:
                continue
            factor = element.factor
            if factor in dropped:
                continue
            factors.add(factor)
            evidence.append(f"{pid}：{element.span.text}")
            if element.extra.get("source") == "caption":
                caption_factors.add(factor)
        # 替换因子
        for old, (new, _note) in self.replacements.get(pid, {}).items():
            factors.discard(old)
            factors.add(new)
        cues = self._linking_cues(proposal)
        return ViewItem(proposal, factors, caption_factors, cues, evidence)

    def _linking_cues(self, proposal: Proposal) -> list[str]:
        """让观众能把这份材料与同批其他材料串起来的线索。"""
        cues: list[str] = []
        for ref in proposal.references:
            if ref.kind is RefKind.ANAPHORA:
                cues.append(f"{proposal.pid} 用同场指代“{ref.span.text}”回指上一载体")
            elif ref.kind is RefKind.DELEGATE:
                cues.append(f"{proposal.pid} 声明“{ref.span.text}”，动作由旁边讲解承载")
            elif ref.kind is RefKind.CAPTION_SOURCE:
                cues.append(f"{proposal.pid} 图注“{ref.span.text}”给出正文未写的条件")
            elif ref.kind is RefKind.REPEAT_STEP:
                cues.append(f"{proposal.pid} 用步骤重复关系锁定同一工件顺序")
        # 共同对象与动作顺序本身也是串接线索
        objects = [e.span.text for e in proposal.elements
                   if e.kind is ElementKind.OBJECT and not e.absent]
        if objects:
            cues.append(f"{proposal.pid} 的对象 {sorted(set(objects))} 与同批材料同名")
        ordered = sorted({
            e.seq for e in proposal.elements
            if e.seq is not None and not e.absent
        })
        if ordered:
            cues.append(f"{proposal.pid} 给出动作顺序 {ordered}")
        return cues

    def audience_view(self, batch: AudienceBatch,
                      include_planned: bool = True) -> list[ViewItem]:
        pids = list(batch.seen)
        if include_planned:
            pids = pids + [p for p in batch.planned if p not in batch.seen]
        return [self._view_item(pid) for pid in pids if pid in self.proposals]

    # ------------------------------------------------------------------
    # 泄密路径
    # ------------------------------------------------------------------
    def find_leak_paths(
        self,
        batch: AudienceBatch,
        include_planned: bool = True,
    ) -> list[LeakPath]:
        view = self.audience_view(batch, include_planned)
        if not view:
            return []
        all_factors = set().union(*(item.factors for item in view))
        all_cues: list[str] = []
        for item in view:
            all_cues.extend(item.cues)

        # 全局受保护的保密组合：无论在哪份稿件的批准上登记，对所有公开观众生效；
        # 签约/闭门批次本身有权接触 A1 类“仅签约可见”内容，不视为泄密。
        signed_batch = self._batch_is_signed(batch)
        guarded: list[tuple[list[str], str]] = []
        for approval in self.resolver.approvals:
            if approval.conditional:
                continue
            if signed_batch and approval.clearance is Clearance.SIGNED_ONLY:
                continue
            for combo in approval.guarded_combos:
                guarded.append((combo, f"{approval.aid} 登记的保密组合"))
        # 工程员对单因子的保密确认同样需要保护
        for item in view:
            pid = item.proposal.pid
            for factor in item.factors:
                clearance = self.resolver.resolve(pid, factor)
                if clearance.clearance is Clearance.SECRET:
                    guarded.append(([factor],
                                    f"{pid} 因子 {factor} 许可为 {clearance.clearance.value}"))
                if (clearance.clearance is Clearance.SIGNED_ONLY
                        and not signed_batch):
                    guarded.append(([factor],
                                    f"{pid} 因子 {factor} 仅签约可见，公开观众无权接触"))

        paths: list[LeakPath] = []
        seen_combos: set[tuple[str, ...]] = set()
        for combo, basis in guarded:
            key = tuple(sorted(combo))
            if key in seen_combos:
                continue
            if not set(combo) <= all_factors:
                continue
            contributed: dict[str, list[str]] = {}
            evidence: list[str] = []
            for item in view:
                part = sorted(set(combo) & item.factors)
                if part:
                    contributed[item.proposal.pid] = part
                    evidence.extend(item.evidence)
            # 单稿即含全部因子时，链接线索要求放宽（同稿顺序/图注即可）
            single_carrier = len(contributed) == 1
            linking = all_cues if (all_cues or single_carrier) else []
            if not single_carrier and not linking:
                continue
            paths.append(LeakPath(
                combo=sorted(combo),
                guarded_basis=basis,
                contributed=contributed,
                linking_cues=linking,
                evidence=sorted(set(evidence)),
            ))
            seen_combos.add(key)
        return paths

    # ------------------------------------------------------------------
    # 改法：可删 / 可换 / 只能给另一组观众
    # ------------------------------------------------------------------
    def edit_options(
        self,
        batch: AudienceBatch,
        paths: list[LeakPath],
    ) -> list[EditOption]:
        options: list[EditOption] = []
        pids = sorted({pid for path in paths for pid in path.contributed})

        for path in paths:
            for pid, part in path.contributed.items():
                proposal = self.proposals[pid]
                # 方案一：删除该稿贡献的因子
                for factor in part:
                    kept, broken = self._premise_impact(proposal, {factor})
                    options.append(EditOption(
                        kind="delete",
                        target_pid=pid,
                        factors=[factor],
                        description=(
                            f"删除 {pid} 中的“{FACTOR_DISPLAY.get(factor, factor)}”"
                            "（含其原文与图注对应字样），使该批观众无法凑齐保密组合"
                        ),
                        principle_kept=sorted(kept),
                        broken_premises=sorted(broken),
                    ))
                # 方案二：替换为已公开的等效表述（需工程员登记替换词）
                for old, (new, note) in self.replacements.get(pid, {}).items():
                    if old in part:
                        options.append(EditOption(
                            kind="replace",
                            target_pid=pid,
                            factors=[old],
                            description=f"将 {pid} 的“{FACTOR_DISPLAY.get(old, old)}”替换为“{note}”",
                            principle_kept=sorted(
                                f for f in self.resolver.substantive_factors(proposal)
                                if f != old
                            ),
                            broken_premises=[],
                        ))
            # 方案三：问题稿件只发给另一组有权观众
            for pid in pids:
                target = self.re_audience.get(pid)
                if target:
                    options.append(EditOption(
                        kind="restrict_audience",
                        target_pid=pid,
                        factors=path.combo,
                        description=(
                            f"{pid} 不进入 {batch.viewers} 材料包，仅向 {target} 发放"
                        ),
                        principle_kept=self.resolver.substantive_factors(
                            self.proposals[pid]
                        ),
                        broken_premises=[],
                    ))
        # 去重
        unique: list[EditOption] = []
        keys = set()
        for option in options:
            key = (option.kind, option.target_pid, tuple(option.factors))
            if key not in keys:
                keys.add(key)
                unique.append(option)
        # 优先保留讲清原理所需公开动作：无 broken_premises 的排前
        unique.sort(key=lambda o: (bool(o.broken_premises), o.kind, o.target_pid))
        return unique

    def _premise_impact(self, proposal: Proposal,
                        dropping: set[str]) -> tuple[set[str], set[str]]:
        remaining = set(self.resolver.substantive_factors(proposal)) - dropping
        broken: set[str] = set()
        for factor in list(remaining):
            required = PREMISES.get(factor, [])
            # 前提只在“被声明需要”时检查：资料未给出的前提不算缺失，
            # 只有原文出现过、又被编审删掉的前提才会让原理讲不清
            if any(req in PREMISES and req not in remaining
                   and req in self.resolver.substantive_factors(proposal)
                   for req in required):
                broken.add(factor)
        return remaining - broken, broken

    # ------------------------------------------------------------------
    # 整组评审
    # ------------------------------------------------------------------
    def review_batch(
        self,
        batch: AudienceBatch,
        include_planned: bool = True,
    ) -> BundleVerdict:
        paths = self.find_leak_paths(batch, include_planned)
        options = self.edit_options(batch, paths)
        reasons: list[str] = []
        broken: list[str] = []

        signed_batch = self._batch_is_signed(batch)
        for item in self.audience_view(batch, include_planned):
            # 许可只按删改/替换后的残余因子核查：删掉的词不再出现在观众视图里
            for factor in sorted(item.factors):
                result = self.resolver.resolve(item.proposal.pid, factor)
                if result.clearance is Clearance.UNCONFIRMED:
                    reasons.append(
                        f"{item.proposal.pid} 的 {factor} 无有效批准或验签，"
                        "关系留待工程员确认，不用相似词补齐"
                    )
                elif (result.clearance is Clearance.SIGNED_ONLY
                      and not signed_batch):
                    reasons.append(
                        f"{item.proposal.pid} 的 {factor} 许可为 "
                        f"{result.clearance.value}，公开观众无权接触"
                    )
                elif result.clearance is Clearance.SECRET:
                    reasons.append(
                        f"{item.proposal.pid} 的 {factor} 被标记暂时保密，"
                        f"{batch.viewers}无权接触"
                    )
            _, item_broken = self._premise_impact(item.proposal, set())
            for factor in item_broken:
                broken.append(f"{item.proposal.pid}：{factor} 缺少讲清原理所需前提")

        if paths:
            reasons.append(
                f"该批观众可由 {len(paths)} 条联合推断路径推出保密关系，"
                "两个可单独发布的草稿同发后越过许可，不能分别盖章"
            )
        if not reasons:
            reasons.append("该组材料在当前观众范围内未发现越许可组合")

        return BundleVerdict(
            bind=",".join(sorted({
                p.bind for p in self.proposals.values()
                if p.pid in batch.seen + batch.planned
            })),
            audience=batch.viewers,
            approvable=not paths and not any(
                "无有效批准" in reason or "无权接触" in reason for reason in reasons
            ),
            reasons=reasons,
            leak_paths=paths,
            options=options,
            broken_premises=sorted(set(broken)),
        )
