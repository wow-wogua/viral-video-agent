import hashlib
import re


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _section_blocks(content: str) -> list[tuple[list[str], str]]:
    """按 Markdown 标题组织正文，并保留完整标题路径。"""
    heading_stack: list[str] = []
    blocks: list[tuple[list[str], str]] = []
    current_lines: list[str] = []

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            blocks.append((heading_stack.copy(), text))
        current_lines.clear()

    for line in content.splitlines():
        match = _HEADING_RE.match(line)
        if not match:
            current_lines.append(line)
            continue

        flush()
        level = len(match.group(1))
        heading_stack[:] = heading_stack[: level - 1]
        heading_stack.append(match.group(2).strip())
    flush()
    return blocks


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _split_long_text(text: str, limit: int) -> list[str]:
    """仅在单段本身过长时按标点优先拆分，最后才退回字符边界。"""
    if len(text) <= limit:
        return [text]

    sentences = [part.strip() for part in re.split(r"(?<=[。！？；.!?;])", text) if part.strip()]
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(sentence[i:i + limit] for i in range(0, len(sentence), limit))
        elif not current or len(current) + len(sentence) <= limit:
            current += sentence
        else:
            pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    return pieces


def _chunk_section(paragraphs: list[str], body_limit: int, overlap: int) -> list[str]:
    expanded = [piece for paragraph in paragraphs for piece in _split_long_text(paragraph, body_limit)]
    chunks: list[str] = []
    current: list[str] = []

    for paragraph in expanded:
        candidate = "\n\n".join([*current, paragraph])
        if current and len(candidate) > body_limit:
            chunks.append("\n\n".join(current))
            overlap_parts: list[str] = []
            overlap_size = 0
            for previous in reversed(current):
                if overlap_parts and overlap_size + len(previous) > overlap:
                    break
                overlap_parts.insert(0, previous)
                overlap_size += len(previous)
            current = overlap_parts
        current.append(paragraph)

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def split_documents(docs: list[dict], chunk_size: int = 1000, chunk_overlap: int = 200) -> list[dict]:
    """标题感知切分；每个 chunk 带稳定 ID、标题路径和完整文档元数据。"""
    if chunk_size <= 100:
        raise ValueError("chunk_size 必须大于 100")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须大于等于 0 且小于 chunk_size")

    chunks: list[dict] = []
    seen_content: set[str] = set()
    for doc in docs:
        sections = _section_blocks(doc["content"])
        if not sections:
            sections = [([doc.get("title", "")], doc["content"])]

        doc_chunk_index = 0
        for heading_path, section_text in sections:
            headings = " > ".join(heading_path)
            prefix = f"文档：{doc.get('title', '')}"
            if headings and headings != doc.get("title"):
                prefix += f"\n章节：{headings}"
            body_limit = max(100, chunk_size - len(prefix) - 2)

            for body in _chunk_section(_paragraphs(section_text), body_limit, chunk_overlap):
                chunk_text = f"{prefix}\n\n{body}".strip()
                normalized = re.sub(r"\s+", " ", chunk_text).strip()
                content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                if content_hash in seen_content:
                    continue
                seen_content.add(content_hash)
                chunk_id = hashlib.sha1(
                    f"{doc['doc_id']}:{doc_chunk_index}:{content_hash}".encode("utf-8")
                ).hexdigest()
                chunk = {key: value for key, value in doc.items() if key != "content"}
                chunk.update({
                    "content": chunk_text,
                    "chunk_id": chunk_id,
                    "chunk_index": doc_chunk_index,
                    "heading_path": headings or doc.get("title", ""),
                    "chunk_hash": content_hash,
                })
                chunks.append(chunk)
                doc_chunk_index += 1

    print(f"[splitter] 标题感知切分为 {len(chunks)} 个去重片段")
    return chunks
