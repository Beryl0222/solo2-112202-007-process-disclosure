"""编审状态的持久化与留痕。

状态分两层：
- 资料包事实（TSV）只读，每次重新装载解析；
- 编审动作（工程员确认、验签、删改模拟、冻结、替换登记）写入工作区 JSON，
  全部带事件序号、时间和操作人，保证能从一次演示回查全部来由。
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import Event


class Store:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "review_state.json"
        self.snapshot_dir = directory / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.data: dict = {
            "overrides": [],        # [pid, factor, clearance, actor]
            "signed": [],           # 已验签 disclosure id
            "replacements": [],     # [pid, old_factor, new_factor, note]
            "re_audience": {},      # pid -> 目标观众
            "dropped": {},          # pid -> [factor]
            "freezes": [],          # 冻结记录
            "incidents": [],        # 会后事故
            "events": [],
        }
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    def save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def log(self, actor: str, action: str, payload: dict | None = None) -> Event:
        seq = len(self.data["events"]) + 1
        event = Event(
            seq=seq,
            time=datetime.now().astimezone().isoformat(timespec="seconds"),
            actor=actor,
            action=action,
            payload=payload or {},
        )
        self.data["events"].append(asdict(event))
        self.save()
        return event

    # ------------------------------------------------------------------
    # 工程员确认
    # ------------------------------------------------------------------
    def add_override(self, pid: str, factor: str, clearance: str, actor: str) -> None:
        self.data["overrides"] = [
            row for row in self.data["overrides"]
            if not (row[0] == pid and row[1] == factor)
        ]
        self.data["overrides"].append([pid, factor, clearance, actor])
        self.log(actor, "工程员确认要素许可", {
            "proposal": pid, "factor": factor, "clearance": clearance,
        })

    # ------------------------------------------------------------------
    # 签名存档验签
    # ------------------------------------------------------------------
    def mark_signed(self, disclosure_id: str, actor: str) -> None:
        if disclosure_id not in self.data["signed"]:
            self.data["signed"].append(disclosure_id)
        self.log(actor, "排练后补入签名公开存档并验签", {
            "disclosure": disclosure_id,
        })

    # ------------------------------------------------------------------
    # 替换与改观众登记
    # ------------------------------------------------------------------
    def add_replacement(self, pid: str, old: str, new: str, note: str,
                        actor: str) -> None:
        self.data["replacements"] = [
            row for row in self.data["replacements"]
            if not (row[0] == pid and row[1] == old)
        ]
        self.data["replacements"].append([pid, old, new, note])
        self.log(actor, "工程员登记替换表述", {
            "proposal": pid, "old": old, "new": new, "note": note,
        })

    def set_re_audience(self, pid: str, audience: str, actor: str) -> None:
        self.data["re_audience"][pid] = audience
        self.log(actor, "工程员限制发放观众", {
            "proposal": pid, "audience": audience,
        })

    def drop_factor(self, pid: str, factor: str, actor: str) -> None:
        current = set(self.data["dropped"].get(pid, []))
        current.add(factor)
        self.data["dropped"][pid] = sorted(current)
        self.log(actor, "编审模拟删除因子", {
            "proposal": pid, "factor": factor,
        })

    def restore_factor(self, pid: str, factor: str, actor: str) -> None:
        current = [f for f in self.data["dropped"].get(pid, []) if f != factor]
        self.data["dropped"][pid] = current
        self.log(actor, "编审恢复因子", {
            "proposal": pid, "factor": factor,
        })

    # ------------------------------------------------------------------
    # 冻结与事故
    # ------------------------------------------------------------------
    def freeze(self, bind: str, pids: list[str], reason: str, actor: str) -> None:
        record = {
            "bind": bind,
            "proposals": pids,
            "reason": reason,
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.data["freezes"].append(record)
        self.log(actor, "冻结继续分发的问题组合", record)

    def record_incident(self, session_id: str, viewers: str,
                        seen: list[str], planned: list[str],
                        over_extended: list[str], contact: str,
                        actor: str) -> dict:
        incident = {
            "session": session_id,
            "viewers": viewers,
            "seen_snapshot": list(seen),
            "planned_snapshot": list(planned),
            "over_extended_factors": over_extended,
            "contact_batch": contact,
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.data["incidents"].append(incident)
        self.log(actor, "展示结束后发现限制扩面，保存各批实际所见并冻结", incident)
        self.save()
        return incident

    # ------------------------------------------------------------------
    # 快照：保存当时各批实际所见
    # ------------------------------------------------------------------
    def snapshot(self, name: str, payload: dict, actor: str) -> Path:
        path = self.snapshot_dir / f"{name}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.log(actor, "保存演示快照", {"name": name, "path": str(path)})
        return path

    # ------------------------------------------------------------------
    # 回查
    # ------------------------------------------------------------------
    def trace(self, keyword: str = "") -> list[dict]:
        if not keyword:
            return self.data["events"]
        # 中文业务词 -> 规范化因子，使回查可以用“低压”这类原话关键词
        from .lexicon import FACTOR_DISPLAY
        aliases = {display: factor for factor, display in FACTOR_DISPLAY.items()}
        needles = [keyword]
        factor = aliases.get(keyword)
        if factor:
            needles.append(factor)
        hits = []
        for event in self.data["events"]:
            blob = json.dumps(event, ensure_ascii=False)
            if any(needle in blob for needle in needles):
                hits.append(event)
        return hits
