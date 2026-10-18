import json
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

from utils.computation import decimal_value
from utils.run_store import utcnow
from utils.semantics import parse_json


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def fetch_document(url):
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("External source requires an HTTP(S) URL")
    try:
        with requests.get(url, timeout=(5, 15), stream=True) as response:
            response.raise_for_status()
            parts, size = [], 0
            for part in response.iter_content(8192):
                size += len(part)
                if size > 2 * 1024 * 1024:
                    raise RuntimeError("External document exceeds the 2 MiB budget")
                parts.append(part)
            body = b"".join(parts).decode(response.encoding or "utf-8")
            content_type = response.headers.get("Content-Type", "")
            final_url = response.url
    except (requests.RequestException, UnicodeError) as exc:
        raise RuntimeError(f"External document fetch failed: {exc}") from exc
    if "html" in content_type:
        parser = PageText()
        parser.feed(body)
        body = "\n".join(parser.parts)
    return {"url": final_url, "text": body, "content_type": content_type, "collected_at": utcnow(),
            "published_at": None, "complete": True, "position_kind": "extracted_text_character"}


def mcp_document(payload, url, known_fetch=False, *, start_index=0):
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("MCP Fetch requires an HTTP(S) URL")
    if type(start_index) is not int or start_index < 0:
        raise ValueError("MCP Fetch start_index must be a non-negative integer")
    content = payload.get("content", [])
    text = payload.get("text")
    if text is None:
        text = content if isinstance(content, str) else "\n".join(
            item["text"] for item in content if item.get("type") == "text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("MCP Fetch returned no document text")
    if len(text.encode()) > 2 * 1024 * 1024:
        raise RuntimeError("MCP document exceeds the 2 MiB budget")
    truncated = bool(re.search(r"content truncated|start_index|<error>", text, re.IGNORECASE))
    complete = known_fetch and start_index == 0 and not truncated
    return {"url": url, "text": text, "content_type": "text/plain", "collected_at": utcnow(),
            "published_at": None, "complete": complete, "position_kind": "extracted_text_character",
            "start_index": start_index,
            "warnings": [] if complete else ["MCP document is partial or completeness is unknown."]}


def align_facts(facts, need, document):
    accepted, warnings = [], []
    for fact in facts:
        span = fact.get("span")
        if (not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span)
                or not 0 <= span[0] < span[1] <= len(document["text"])):
            raise ValueError("External fact has an invalid source position")
        excerpt = document["text"][span[0]:span[1]]
        for key in ("value", "unit", "region", "observed_at"):
            if not isinstance(fact.get(key), str) or fact[key] not in excerpt:
                raise ValueError(f"External fact {key} is not present at the cited source position")
        decimal_value(fact["value"])
        try:
            observed = datetime.fromisoformat(fact["observed_at"])
            start, end = datetime.fromisoformat(need["start"]), datetime.fromisoformat(need["end"])
            if observed.tzinfo is None or start.tzinfo is None or end.tzinfo is None:
                raise ValueError("Evidence observation times require explicit timezones")
            aligned = (start <= observed < end and fact["region"] == need["region"]
                       and fact["unit"] == need["unit"] and fact.get("variable") == need["variable"])
        except (KeyError, TypeError) as exc:
            raise ValueError("Evidence need requires variable, region, unit and absolute start/end") from exc
        if not aligned:
            warnings.append(f"Unaligned evidence excluded: {fact.get('variable')} / {fact['observed_at']}")
            continue
        accepted.append({**fact, "source_url": document["url"], "collected_at": document["collected_at"],
                         "published_at": document["published_at"], "excerpt": excerpt})
    return accepted, warnings


def extract_evidence(document, need, call_model):
    if not document["complete"]:
        return {"sources": [document], "facts": [], "warnings": ["Incomplete document is discovery only."]}
    if len(document["text"]) > 16000:
        document = {**document, "text": document["text"][:16000], "complete": False}
        return {"sources": [document], "facts": [], "warnings": ["Document exceeds extraction budget; narrow the source."]}
    extracted = parse_json(call_model(
        "fast", "generate_response",
        f"\nEvidence need: {json.dumps(need, ensure_ascii=False)}\nDocument:\n{document['text']}",
        request_type="query", node="extraction"))
    if not isinstance(extracted.get("facts"), list):
        raise ValueError("External extraction requires a facts list")
    facts, warnings = align_facts(extracted["facts"], need, document)
    if not facts:
        warnings.append("No comparable observed facts; source is background/discovery only.")
    return {"sources": [document], "facts": facts, "warnings": warnings}


def extract_structured(document, need, mapping):
    try:
        payload = json.loads(document["text"])
        records = payload
        path = mapping.get("records_path", [])
        for key in path:
            records = records[key]
        if not isinstance(records, list):
            raise ValueError("Structured source records_path must point to a list")
        facts, warnings = [], []
        for index, record in enumerate(records):
            fact = {key: str(record[mapping[key]]) for key in ("value", "unit", "region", "observed_at")}
            fact["variable"] = str(record[mapping["variable"]])
            text = json.dumps(record, ensure_ascii=False)
            fact["span"] = [0, len(text)]
            selected, limits = align_facts([fact], need, {**document, "text": text})
            for item in selected:
                item.pop("span")
                item.update(source_position="/" + "/".join(
                                str(key).replace("~", "~0").replace("/", "~1") for key in [*path, index]),
                            position_kind="json_pointer", field_mapping=mapping)
            facts.extend(selected)
            warnings.extend(limits)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Structured evidence mapping failed: {exc}") from exc
    return {"sources": [document], "facts": facts, "warnings": warnings}
