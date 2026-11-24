# 新工艺展示中的公开先例与保密边界

业务资料使用虚构编号和合成叙述。文本保持来件拼写和措辞。各表是独立的来源记录。
TSV 文件采用 UTF-8，首行为列名。行首 id 是该表的稳定记录号，空格和标点属于原文，空单元格表示来件未填。
日期时间采用所在地本地时间。资料内注明为编号列表的字段用竖线分隔。

## 资料字段

- `materials/disclosures.tsv`。edition 是同一展示物的发行版，audience 为当时实际观众。context 是文字出现的装置或段落。
- `materials/proposal.tsv`。stage 表示编审方计划的载体，bind 指拟一起发放的内容组。
- `materials/approvals.tsv`。proposal 可关联拟发草稿，scope 保留工程员原话，canonical 是登记到的原件编号。
- `materials/sessions.tsv`。seen 是实际已被观众看到的稿件编号，planned 是当前待处理组合，均可多条。

## 运行资料检查

使用 CPython 3.11.2 和标准库。资料检查仅读取输入。

```sh
python3 pack_check.py
python3 -m unittest -v
```

## 研发编审工具（rdreview）

在资料检查之上做语义编审：识别要素、动作先后、条件与描述强度，判断一组相互
约束的要素是否在同一份可确认公开记录、同一实施条件下同时出现，并按观众实际
接触的全部材料核查联合推断。详见 [`rdreview/README.md`](rdreview/README.md)。

```sh
python3 -I rdreview/demo.py            # 端到端编审故事线（状态写临时目录）
python3 -I rdreview/cli.py list        # 记录、实施方式分组、批准、观众批次
python3 -I rdreview/cli.py review S1   # 按观众批次评审（泄密路径与改法）
python3 -I rdreview/cli.py verify D4   # 验签签名存档后重新判断缺证实施方式
python3 -I rdreview/cli.py incident S1 # 会后限制扩面：保存所见、冻结、联系批次
python3 -I rdreview/cli.py trace 低压  # 回查先例出处、许可与不能合并发的来由
```

编审状态写入 `review_workspace/`（已忽略），资料包始终只读。
