"""
policies/loader.py — Parse policies.md into individual documents,
then filter by manifest.json status and effective_date vs APP_TODAY.
"""
import json
import re
from datetime import date
from typing import Optional
from config import POLICIES_PATH, MANIFEST_PATH, APP_TODAY_STR

# ── Parse APP_TODAY once ──────────────────────────────────────────────────────
APP_TODAY: date = date.fromisoformat(APP_TODAY_STR)


def _load_manifest() -> dict[str, dict]:
    """Load manifest.json and index by doc_id."""
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        entries = json.load(f)
    return {e["doc_id"]: e for e in entries}


def _split_policies(text: str) -> list[dict]:
    """
    Split policies.md on top-level '#' headings.
    Each chunk contains: title, raw_text, and extracted doc_id.
    """
    # Split at every line starting with exactly one '#' (not ## or ###)
    parts = re.split(r"(?m)^(?=#[^#])", text)
    docs = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.splitlines()
        title = lines[0].lstrip("#").strip()
        # Try to find Document ID line
        doc_id_match = re.search(r"\*\*Document ID:\*\*\s*([\w_]+)", part)
        if not doc_id_match:
            continue
        doc_id = doc_id_match.group(1)
        docs.append({"doc_id": doc_id, "title": title, "text": part})
    return docs


def _extract_sections(text: str) -> list[dict]:
    """
    Split a policy document text into sections by '## §' or '### §' headings.
    Returns list of {section_id, heading, text}.
    """
    # Match lines like '## §2.1 Return window'
    pattern = re.compile(r"(?m)^(#{2,3})\s+(§[\d.]+)\s+(.*)")
    matches = list(pattern.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        section_id = m.group(2)
        heading = m.group(3)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        sections.append({
            "section_id": section_id,
            "heading": heading,
            "text": section_text,
        })
    return sections


class PolicyStore:
    """
    Holds all current, applicable policy documents and their sections.
    Documents are filtered:
      - status must be 'current'
      - effective_date must be <= APP_TODAY
    Future documents (effective_date > APP_TODAY) are kept separately
    so we can mention them as upcoming changes.
    """

    def __init__(self):
        self.current_docs: dict[str, dict] = {}   # doc_id -> {meta, sections}
        self.future_docs: dict[str, dict] = {}    # doc_id -> {meta, title, effective_date}
        self._load()

    def _load(self):
        manifest = _load_manifest()
        with open(POLICIES_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        raw_docs = _split_policies(raw)

        for doc in raw_docs:
            doc_id = doc["doc_id"]
            meta = manifest.get(doc_id)
            if not meta:
                continue  # not in manifest — skip

            eff_date = date.fromisoformat(meta["effective_date"])

            if meta["status"] != "current":
                continue  # superseded — never use

            if eff_date > APP_TODAY:
                # Future policy — note it, don't apply it
                self.future_docs[doc_id] = {
                    "doc_id": doc_id,
                    "title": doc["title"],
                    "effective_date": meta["effective_date"],
                    "text": doc["text"],
                }
                continue

            sections = _extract_sections(doc["text"])
            self.current_docs[doc_id] = {
                "doc_id": doc_id,
                "title": doc["title"],
                "effective_date": meta["effective_date"],
                "full_text": doc["text"],
                "sections": sections,
            }

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Keyword-based search across all current policy sections.
        Returns top_k most relevant sections with doc_id and section_id.
        Scores each section by count of query words found in it.
        Also checks future docs and appends a note about upcoming changes.
        """
        query_lower = query.lower()
        keywords = re.findall(r"\w+", query_lower)
        results: list[tuple[int, dict]] = []

        for doc_id, doc in self.current_docs.items():
            for sec in doc["sections"]:
                text_lower = sec["text"].lower()
                score = sum(1 for kw in keywords if kw in text_lower)
                if score > 0:
                    results.append((score, {
                        "doc_id": doc_id,
                        "section": sec["section_id"],
                        "heading": sec["heading"],
                        "text": sec["text"],
                    }))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)
        hits = [r[1] for r in results[:top_k]]

        # Append upcoming policy note if relevant
        for doc_id, future in self.future_docs.items():
            text_lower = future["text"].lower()
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                hits.append({
                    "doc_id": doc_id,
                    "section": "future",
                    "heading": f"Upcoming change (effective {future['effective_date']})",
                    "text": future["text"][:800],  # brief excerpt
                    "is_future": True,
                })

        return hits

    def get_section(self, doc_id: str, section_id: str) -> Optional[str]:
        """Return text of a specific section."""
        doc = self.current_docs.get(doc_id)
        if not doc:
            return None
        for sec in doc["sections"]:
            if sec["section_id"] == section_id:
                return sec["text"]
        return None


# Singleton — loaded once at startup
_store: Optional[PolicyStore] = None


def get_policy_store() -> PolicyStore:
    global _store
    if _store is None:
        _store = PolicyStore()
    return _store
