import re


EVIDENCE_REF_RE = re.compile(r"\b(ev_[a-f0-9]{8,32})\b")


def validate_claims(claims: list[dict], evidence: list[dict]) -> tuple[bool, str]:
    valid_ids = {item["evidence_id"] for item in evidence}
    for claim in claims:
        evidence_ids = claim.get("evidence_ids", [])
        if any(item not in valid_ids for item in evidence_ids):
            return False, "claim references unknown evidence_id"
        if claim.get("claim_type") == "observation" and not evidence_ids:
            return False, "observation has no evidence"
    return True, ""


def validate_report_references(content: str, evidence: list[dict]) -> tuple[bool, str]:
    valid_ids = {item["evidence_id"] for item in evidence}
    unknown = sorted(set(EVIDENCE_REF_RE.findall(content)) - valid_ids)
    if unknown:
        return False, f"report references unknown evidence_id: {', '.join(unknown)}"
    return True, ""


def finalize_report(content: str, claims: list[dict], evidence: list[dict]) -> str:
    claim_lines = []
    for index, claim in enumerate(claims, 1):
        refs = " ".join(f"[{item}]" for item in claim.get("evidence_ids", [])) or "（无直接数值证据）"
        label = {"observation": "数据观察", "inference": "分析推断", "recommendation": "行动建议"}.get(claim.get("claim_type"), "分析推断")
        claim_lines.append(f"{index}. **{label}**：{claim.get('claim', '')} {refs}")
    evidence_lines = ["| 编号 | 类型 | 标题 | 来源 |", "|---|---|---|---|"]
    for item in evidence:
        title = str(item.get("title", "Evidence")).replace("|", "\\|")
        url = item.get("source_url")
        source = f"[打开来源]({url})" if url else "本地知识库"
        evidence_lines.append(f"| {item['evidence_id']} | {item.get('source_type', '')} | {title} | {source} |")
    appendix = "\n\n## 结构化结论与引用\n\n" + ("\n".join(claim_lines) if claim_lines else "当前没有通过校验的结构化结论。")
    appendix += "\n\n## 数据附录（程序生成）\n\n" + "\n".join(evidence_lines)
    appendix += "\n\n> 局限：结论仅适用于本次采集到的公开 B 站样本，不代表整个平台或整个行业。"
    return content.rstrip() + appendix
