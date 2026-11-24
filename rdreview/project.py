"""研发编审项目门面：把资料包、状态与各分析引擎组装成一次完整工作流。"""
from __future__ import annotations

from pathlib import Path

from .clearance import ClearanceResolver, GenericOverreach
from .inference import InferenceEngine
from .loader import load_pack
from .models import (
    AudienceBatch,
    BundleVerdict,
    Clearance,
    Disclosure,
    Phase,
    RefKind,
    Status,
)
from .precedent import ImplGrouping, build_impl_groups, check_precedent
from .store import Store


class ReviewProject:
    def __init__(self, materials_dir: Path, work_dir: Path) -> None:
        self.materials_dir = materials_dir
        self.store = Store(work_dir)
        self.reload()

    def reload(self) -> None:
        pack = load_pack(self.materials_dir)
        self.disclosures: list[Disclosure] = pack["disclosures"]
        self.proposals = pack["proposals"]
        self.approvals = pack["approvals"]
        self.sessions: list[AudienceBatch] = pack["sessions"]

        # 应用验签状态
        for disclosure in self.disclosures:
            disclosure.signed = disclosure.rid in self.store.data["signed"]
            for ref in disclosure.references:
                if ref.kind is RefKind.SAME_IMPL and disclosure.signed:
                    ref.status = Status.VERIFIED
                    ref.verified_against = disclosure.rid

        self.grouping: ImplGrouping = build_impl_groups(self.disclosures)
        self.resolver = ClearanceResolver(
            self.disclosures, self.proposals, self.approvals
        )
        # 应用工程员确认
        for pid, factor, clearance_value, _actor in self.store.data["overrides"]:
            self.resolver.set_override(
                pid, factor, Clearance(clearance_value), actor="状态恢复"
            )
        self.engine = InferenceEngine(
            self.proposals, self.resolver, self.disclosures
        )
        # 应用替换、改观众、删改
        for pid, old, new, note in self.store.data["replacements"]:
            self.engine.replacements.setdefault(pid, {})[old] = (new, note)
        for pid, audience in self.store.data["re_audience"].items():
            self.engine.re_audience[pid] = audience
        for pid, factors in self.store.data["dropped"].items():
            self.engine.dropped[pid] = set(factors)

    # ------------------------------------------------------------------
    # 验签：排练后补到带签名公开存档，重新判断以前缺证的实施方式
    # ------------------------------------------------------------------
    def verify_signed_archive(self, disclosure_id: str, actor: str) -> dict:
        """排练后补到带签名公开存档：验签该页及其同实施方式链上的签名页。"""
        disclosure = self._disclosure(disclosure_id)
        self.store.mark_signed(disclosure_id, actor)
        # 续页验签时，它显式接续的同实施方式签名页一并验到
        chain_ids = {disclosure_id}
        for ref in disclosure.references:
            if ref.kind is not RefKind.SAME_IMPL:
                continue
            target = next(
                (d for d in self.disclosures if d.edition == ref.target), None
            )
            if target is not None:
                chain_ids.add(target.rid)
                self.store.mark_signed(target.rid, actor)
        self.reload()
        disclosure = self._disclosure(disclosure_id)
        restored: list[str] = []
        chain_records = [d for d in self.disclosures if d.rid in chain_ids]
        chain_factors: set[str] = set()
        for record in chain_records:
            chain_factors |= record.positive_factors
        # 验签后：签名链上明确公开过的因子，在条件性批准下恢复可公开评估
        for proposal in self.proposals:
            for factor in self.resolver.substantive_factors(proposal):
                if factor not in chain_factors:
                    continue
                result = self.resolver.resolve(proposal.pid, factor)
                if result.clearance is Clearance.PUBLIC:
                    restored.append(f"{proposal.pid}:{factor}")
        # 链上任一页明确缺记/否定的因子，提示仍无公开支持
        still_missing = sorted({
            e.factor
            for record in chain_records
            for e in record.elements
            if e.absent
        })
        self.store.log(actor, "验签后重新判断缺证实施方式", {
            "disclosure": disclosure_id,
            "verified_chain": sorted(chain_ids),
            "restored_to_public_review": sorted(set(restored)),
            "still_unsupported": still_missing,
        })
        return {
            "disclosure": disclosure_id,
            "impl_group": disclosure.impl_group,
            "verified_chain": sorted(chain_ids),
            "restored": sorted(set(restored)),
            "still_unsupported": still_missing,
            "note": (
                "恢复的仅限签名页明确公开过的要素；链上缺记/否定的条件"
                "（如未说明的低压）仍无公开支持"
            ),
        }

    # ------------------------------------------------------------------
    # 先例核查
    # ------------------------------------------------------------------
    def precedent_for_factors(self, factors: list[str]):
        return check_precedent(factors, self.disclosures, self.grouping)

    def precedent_for_proposal(self, pid: str):
        proposal = self._proposal(pid)
        factors = self.resolver.substantive_factors(proposal)
        hits, traps = check_precedent(factors, self.disclosures, self.grouping)
        return factors, hits, traps

    # ------------------------------------------------------------------
    # 通用性越界
    # ------------------------------------------------------------------
    def generic_overreach(self) -> list[GenericOverreach]:
        return self.resolver.check_generic_overreach()

    # ------------------------------------------------------------------
    # 观众批次评审
    # ------------------------------------------------------------------
    def review_session(self, sid: str,
                       include_planned: bool = True) -> BundleVerdict:
        batch = self._session(sid)
        verdict = self.engine.review_batch(batch, include_planned)
        # 补上先例、拆分陷阱、缺证关系、通用性越界（陷阱按理由去重）
        seen_traps: set[tuple] = set()
        for pid in batch.seen + batch.planned:
            if pid not in {p.pid for p in self.proposals}:
                continue
            _factors, hits, traps = self.precedent_for_proposal(pid)
            verdict.precedent_hits.extend(hits)
            for trap in traps:
                key = (tuple(trap.across_records), trap.reason)
                if key not in seen_traps:
                    seen_traps.add(key)
                    verdict.split_traps.append(trap)
        # 先例同样去重
        unique_hits: dict[tuple, object] = {}
        for hit in verdict.precedent_hits:
            unique_hits[(hit.record_id, tuple(hit.factors))] = hit
        verdict.precedent_hits = list(unique_hits.values())
        verdict.unconfirmed_relations = list(self.grouping.unconfirmed)
        verdict.generic_overreach = [
            f"{g.proposal_id}: {g.note}" for g in self.generic_overreach()
        ]
        return verdict

    # ------------------------------------------------------------------
    # 会后事故：限制被扩到公开观众
    # ------------------------------------------------------------------
    def handle_post_event_incident(self, sid: str, actor: str) -> dict:
        batch = self._session(sid)
        if batch.phase not in (Phase.ENDED, Phase.DISTRIBUTED):
            raise ValueError(
                f"{sid} 当前阶段为 {batch.phase.value}，按流程仅在展示结束/已发后立案"
            )
        # 用含 planned 的完整视图找出被扩面的限制因子
        full_view = self.engine.review_batch(batch, include_planned=True)
        over_extended = sorted({
            factor
            for path in full_view.leak_paths
            for factor in path.combo
        })
        # 保存当时各批实际所见（只含 seen，不含尚未发出的 planned）
        snapshot_payload = {
            "incident_session": sid,
            "batches": [
                {
                    "sid": other.sid,
                    "viewers": other.viewers,
                    "phase": other.phase.value,
                    "actually_seen": list(other.seen),
                    "planned_at_time": list(other.planned),
                }
                for other in self.sessions
            ],
            "over_extended_factors": over_extended,
        }
        snapshot_path = self.store.snapshot(
            f"incident_{sid}", snapshot_payload, actor
        )
        # 冻结有问题的组合（planned 中导致扩面的稿件）
        problem_pids = sorted({
            pid
            for path in full_view.leak_paths
            for pid in path.contributed
            if pid in batch.planned
        })
        if problem_pids:
            self.store.freeze(
                bind=",".join(sorted({
                    self._proposal(p).bind for p in problem_pids
                })),
                pids=problem_pids,
                reason=(
                    "会后资料把仅在闭门场出现的限制扩到公开观众，"
                    f"越界因子 {over_extended}"
                ),
                actor=actor,
            )
        incident = self.store.record_incident(
            session_id=sid,
            viewers=batch.viewers,
            seen=list(batch.seen),
            planned=list(batch.planned),
            over_extended=over_extended,
            contact=batch.viewers,
            actor=actor,
        )
        incident["snapshot"] = str(snapshot_path)
        incident["frozen"] = problem_pids
        return incident

    # ------------------------------------------------------------------
    def trace(self, keyword: str = "") -> list[dict]:
        return self.store.trace(keyword)

    def _disclosure(self, rid: str) -> Disclosure:
        result = next((d for d in self.disclosures if d.rid == rid), None)
        if result is None:
            raise KeyError(f"未知旧展示物 {rid}")
        return result

    def _proposal(self, pid: str):
        result = next((p for p in self.proposals if p.pid == pid), None)
        if result is None:
            raise KeyError(f"未知拟演示稿 {pid}")
        return result

    def _session(self, sid: str) -> AudienceBatch:
        result = next((s for s in self.sessions if s.sid == sid), None)
        if result is None:
            raise KeyError(f"未知观众批次 {sid}")
        return result
