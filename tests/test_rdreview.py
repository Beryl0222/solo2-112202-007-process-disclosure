"""研发编审工具的单元测试。

用临时工作区隔离状态，资料包仍读 materials/（只读）。测试覆盖需求中的
关键判断：解析要素与引用、拆分陷阱、同实施方式续页并组、验签恢复、
观众联合推断、删词仍可推出、单发/同发差异、事故冻结与回查。
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from rdreview.clearance import ClearanceResolver
from rdreview.lexicon import FACTOR_DISPLAY
from rdreview.loader import load_pack
from rdreview.models import Clearance, Phase, RefKind, Status
from rdreview.parser import parse_text
from rdreview.precedent import build_impl_groups, check_precedent
from rdreview.project import ReviewProject

MATERIALS = Path(__file__).resolve().parent.parent / "materials"


class ParserTest(unittest.TestCase):
    def test_extracts_objects_actions_conditions_and_sequence(self):
        elements, references = parse_text(
            "弹性底座，在低压时分两段抬升，第一段后保持接触。", "X"
        )
        factors = {e.factor for e in elements}
        self.assertIn("object.elastic_base", factors)
        self.assertIn("condition.low_pressure", factors)
        self.assertIn("action.two_stage_lift", factors)
        self.assertIn("action.hold_contact", factors)
        sequenced = {e.factor: e.seq for e in elements if e.seq is not None}
        self.assertEqual(sequenced.get("condition.low_pressure"), 1)

    def test_absence_is_marked_not_claimed(self):
        elements, _ = parse_text("但未说明低压。", "X")
        absence = next(e for e in elements if e.factor == "condition.low_pressure")
        self.assertTrue(absence.absent)

    def test_same_impl_reference_distinguished_from_caption(self):
        _, references = parse_text("本页接着 H1 的样架；图注说明正是低压。", "X")
        kinds = {r.kind for r in references}
        self.assertIn(RefKind.SAME_IMPL, kinds)
        self.assertIn(RefKind.CAPTION_SOURCE, kinds)
        same_impl = next(r for r in references if r.kind is RefKind.SAME_IMPL)
        self.assertEqual(same_impl.target, "H1")

    def test_caption_inner_factors_remain_visible(self):
        elements, references = parse_text("图注说明正是低压，两段动作。", "X")
        self.assertTrue(any(r.kind is RefKind.CAPTION_SOURCE for r in references))
        caption_factors = {
            e.factor for e in elements if e.extra.get("source") == "caption"
        }
        self.assertIn("condition.low_pressure", caption_factors)
        self.assertIn("action.two_stage", caption_factors)

    def test_delegation_and_anaphora_are_separate_ref_kinds(self):
        _, refs = parse_text("动作按旁边口头提示。", "X")
        self.assertEqual(refs[0].kind, RefKind.DELEGATE)
        _, refs = parse_text("刚才那台样架，在低压下分两段抬升。", "X")
        self.assertEqual(refs[0].kind, RefKind.ANAPHORA)


class PrecedentTest(unittest.TestCase):
    def setUp(self) -> None:
        pack = load_pack(MATERIALS)
        self.disclosures = pack["disclosures"]
        self.grouping = build_impl_groups(self.disclosures)

    def test_no_public_precedent_before_verification(self):
        # 全部记录未验签：闭门 D3 与待核 D4 都不能支撑公开先例
        hits, traps = check_precedent(
            ["object.elastic_base", "action.two_stage_lift",
             "condition.low_pressure"],
            self.disclosures, self.grouping,
        )
        self.assertEqual(hits, [])
        self.assertTrue(traps)
        reasons = " ".join(t.reason for t in traps)
        self.assertIn("闭门场", reasons)
        self.assertIn("未验签", reasons)

    def test_unrelated_records_never_merge_by_similarity(self):
        # D1 的弹性底座 与 D2 的两段抬升在不同装置上，必须各自成陷阱
        hits, traps = check_precedent(
            ["object.elastic_base", "action.two_stage"],
            self.disclosures, self.grouping,
        )
        self.assertEqual(hits, [])
        record_sets = [tuple(t.across_records) for t in traps]
        self.assertIn(("D1",), record_sets)
        self.assertIn(("D2",), record_sets)

    def test_verified_chain_allows_cross_page_same_impl(self):
        d1 = next(d for d in self.disclosures if d.rid == "D1")
        d4 = next(d for d in self.disclosures if d.rid == "D4")
        d1.signed = d4.signed = True
        for ref in d4.references:
            if ref.kind is RefKind.SAME_IMPL:
                ref.status = Status.VERIFIED
        grouping = build_impl_groups(self.disclosures)
        hits, _ = check_precedent(
            ["object.elastic_base", "action.two_stage_lift",
             "action.hold_contact"],
            self.disclosures, grouping,
        )
        self.assertEqual(len(hits), 1)
        self.assertFalse(hits[0].same_record)
        self.assertTrue(hits[0].same_impl)
        self.assertEqual(set(hits[0].record_id.split("+")), {"D1", "D4"})

    def test_low_pressure_still_unsupported_after_verification(self):
        d1 = next(d for d in self.disclosures if d.rid == "D1")
        d4 = next(d for d in self.disclosures if d.rid == "D4")
        d1.signed = d4.signed = True
        for ref in d4.references:
            if ref.kind is RefKind.SAME_IMPL:
                ref.status = Status.VERIFIED
        grouping = build_impl_groups(self.disclosures)
        hits, traps = check_precedent(
            ["object.elastic_base", "action.two_stage_lift",
             "condition.low_pressure"],
            self.disclosures, grouping,
        )
        self.assertEqual(hits, [])
        self.assertTrue(
            any("明确未记录" in t.reason and "D4" in t.reason for t in traps)
        )


class ProjectWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.work = Path(self.tmp) / "work"
        self.project = ReviewProject(MATERIALS, self.work)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_signed_batch_can_stamp_but_public_cannot(self):
        s2 = self.project.review_session("S2")
        self.assertTrue(s2.approvable)
        s1 = self.project.review_session("S1")
        self.assertFalse(s1.approvable)
        self.assertTrue(s1.leak_paths)

    def test_joint_inference_across_board_talk_and_handout(self):
        verdict = self.project.review_session("S1")
        combos = {tuple(sorted(path.combo)) for path in verdict.leak_paths}
        self.assertIn(
            ("action.two_stage_lift", "condition.low_pressure"), combos
        )
        # P4 的图注必须被识别为低压来源
        p4 = next(p for p in self.project.proposals if p.pid == "P4")
        caption = [
            e for e in p4.elements if e.extra.get("source") == "caption"
        ]
        self.assertTrue(any(e.factor == "condition.low_pressure"
                            for e in caption))
        # 串接线索里应包含同场指代与图注
        cues = " ".join(
            cue for path in verdict.leak_paths for cue in path.linking_cues
        )
        self.assertIn("刚才那台样架", cues)
        self.assertIn("图注", cues)

    def test_deleting_one_word_keeps_inference_when_caption_remains(self):
        # 只删 P2 的低压词：P4 图注仍带低压，保密组合依旧可被推出
        self.project.store.drop_factor("P2", "condition.low_pressure", "编审员")
        self.project.reload()
        verdict = self.project.review_session("S1")
        remaining = {
            factor
            for path in verdict.leak_paths
            for factor in path.combo
        }
        self.assertIn("condition.low_pressure", remaining)
        contributor = {
            pid
            for path in verdict.leak_paths
            for pid in path.contributed
        }
        self.assertIn("P4", contributor)

    def test_verify_restores_supported_factors_only(self):
        result = self.project.verify_signed_archive("D4", "张工")
        self.assertEqual(set(result["verified_chain"]), {"D1", "D4"})
        self.assertIn("condition.low_pressure", result["still_unsupported"])
        d4 = next(d for d in self.disclosures_() if d.rid == "D4")
        self.assertTrue(d4.signed)

    def disclosures_(self):
        return self.project.disclosures

    def test_generic_claim_flagged_with_single_example(self):
        findings = self.project.generic_overreach()
        p1 = next(f for f in findings if f.proposal_id == "P1")
        self.assertEqual(p1.supported_examples, ["弹性底座"])

    def test_separate_drafts_pass_but_bundle_does_not(self):
        # 工程员确认 P2 除低压外的要素可公开
        for factor in ("action.two_stage_lift", "action.hold_contact",
                       "action.lift"):
            self.project.store.add_override(
                "P2", factor, Clearance.PUBLIC.value, "李工"
            )
        self.project.store.drop_factor("P2", "condition.low_pressure", "编审员")
        self.project.reload()
        # 补场 S3 只有 P1+P2，且低压已删：无泄密路径
        s3 = self.project.review_session("S3")
        self.assertEqual(s3.leak_paths, [])
        # 同发加入 P4（图注带低压）后越过许可，整组不能盖章
        s1 = self.project.review_session("S1")
        self.assertTrue(s1.leak_paths)
        self.assertFalse(s1.approvable)

    def test_post_event_incident_freezes_and_preserves_seen(self):
        incident = self.project.handle_post_event_incident("S1", "编审员")
        self.assertEqual(incident["seen_snapshot"], ["P1", "P2"])
        self.assertEqual(incident["frozen"], ["P4"])
        self.assertEqual(incident["contact_batch"], "公开登记组")
        snapshot = Path(incident["snapshot"])
        self.assertTrue(snapshot.exists())
        freezes = self.project.store.data["freezes"]
        self.assertTrue(any("P4" in fz["proposals"] for fz in freezes))

    def test_incident_rejected_before_event_ends(self):
        s3 = next(s for s in self.project.sessions if s.sid == "S3")
        self.assertEqual(s3.phase, Phase.UNRELEASED)
        with self.assertRaises(ValueError):
            self.project.handle_post_event_incident("S3", "编审员")

    def test_trace_returns_full_rationale_chain(self):
        self.project.verify_signed_archive("D4", "张工")
        self.project.store.add_override(
            "P2", "condition.low_pressure", Clearance.SECRET.value, "李工"
        )
        events = self.project.trace("低压")
        self.assertTrue(events)
        self.assertTrue(any("保密" in e["action"] or "确认" in e["action"]
                            for e in events))

    def test_edit_options_rank_principle_preserving_first(self):
        verdict = self.project.review_session("S1")
        self.assertTrue(verdict.options)
        # 第一条改法不应破坏讲清原理所需的前提
        self.assertEqual(verdict.options[0].broken_premises, [])
        # 删除两段抬升应被标出会使“保持接触”失去前提
        destructive = next(
            (o for o in verdict.options
             if o.kind == "delete"
             and "action.two_stage_lift" in o.factors),
            None,
        )
        self.assertIsNotNone(destructive)
        self.assertIn("action.hold_contact", destructive.broken_premises)

    def test_unconfirmed_relations_are_not_filled_by_similar_words(self):
        verdict = self.project.review_session("S1")
        self.assertTrue(any("D4" in note for note in
                            verdict.unconfirmed_relations))
        # 工程员确认前，P2 因子保持待确认
        resolver: ClearanceResolver = self.project.resolver
        result = resolver.resolve("P2", "condition.low_pressure")
        self.assertEqual(result.clearance, Clearance.UNCONFIRMED)

    def test_ingest_keeps_state_and_dedupes_traps(self):
        # 先做一次验签与确认，再重新装载，状态必须保留
        self.project.verify_signed_archive("D4", "张工")
        self.project.reload()
        d4 = next(d for d in self.project.disclosures if d.rid == "D4")
        self.assertTrue(d4.signed)
        verdict = self.project.review_session("S1")
        reasons = [t.reason for t in verdict.split_traps]
        self.assertEqual(len(reasons), len(set(reasons)))
        # 验签事件已留痕
        self.assertTrue(any(
            e["action"] == "排练后补入签名公开存档并验签"
            for e in self.project.trace()
        ))


if __name__ == "__main__":
    unittest.main()
