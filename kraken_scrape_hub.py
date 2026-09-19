#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

TEXT_KEYS = ("text", "content", "body", "message", "description", "bio", "title", "caption")
AUTHOR_KEYS = ("author", "user", "username", "handle", "screen_name", "account", "owner")
PLATFORM_KEYS = ("platform", "network", "source", "site", "provider", "origin")
URL_KEYS = ("url", "link", "href", "source_url", "profile_url", "permalink")
TIMESTAMP_KEYS = ("timestamp", "created_at", "published_at", "date", "time")
INTERESTING_KEYS = set(TEXT_KEYS + AUTHOR_KEYS + PLATFORM_KEYS + URL_KEYS + TIMESTAMP_KEYS)

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d(). -]{7,}\d)")
URL_RE = re.compile(r"https?://[^\s<>'\"()]+", re.I)
MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9_\.]{2,32})")
HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_]{2,64})")
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ']+")

POSITIVE_WORDS = {
    "good", "great", "excellent", "positive", "success", "trusted", "safe", "secure",
    "happy", "love", "strong", "growth", "benefit", "win", "improve", "resilient",
}
NEGATIVE_WORDS = {
    "bad", "risk", "negative", "fail", "failure", "breach", "leak", "exposed", "fraud",
    "unsafe", "attack", "abuse", "scam", "critical", "angry", "hate", "threat",
}
BREACH_PATTERNS = {
    "email": EMAIL_RE,
    "phone": PHONE_RE,
    "password": re.compile(r"(?i)\b(?:pass(?:word|wd)?|pwd)\b\s*[:=]\s*\S+"),
    "token": re.compile(r"(?i)\b(?:api[_ -]?key|token|secret|bearer|session(?:id)?)\b\s*[:=]\s*[A-Za-z0-9._\-]{8,}"),
    "card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credential_dump": re.compile(r"(?i)\bcombo\b|\bdump\b|\bcredential(?:s)?\b|\bbreach(?:ed)?\b|\bleak(?:ed|s)?\b"),
}


def normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def nested_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(nested_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(nested_strings(item))
        return strings
    return []


def pick_first_string(record: dict[str, Any], names: tuple[str, ...]) -> str | None:
    lowered = {normalize_key(key): value for key, value in record.items()}
    for name in names:
        values = nested_strings(lowered.get(name))
        if values:
            return values[0]
    return None


def is_candidate_record(value: dict[str, Any]) -> bool:
    lowered_keys = {normalize_key(key) for key in value}
    return bool(lowered_keys & INTERESTING_KEYS)


def inherit_context(context: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    inherited = dict(context)
    for key, item in value.items():
        normalized = normalize_key(key)
        if normalized in INTERESTING_KEYS and not isinstance(item, (dict, list)):
            inherited[key] = item
    return inherited


def iter_candidate_records(
    value: Any,
    path: str = "root",
    context: dict[str, Any] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    matches: list[tuple[str, dict[str, Any]]] = []
    context = context or {}
    if isinstance(value, dict):
        next_context = inherit_context(context, value)
        if is_candidate_record(value):
            matches.append((path, {**context, **value}))
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                matches.extend(iter_candidate_records(item, f"{path}.{key}", next_context))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            matches.extend(iter_candidate_records(item, f"{path}[{index}]", context))
    elif value not in (None, ""):
        matches.append((path, {"text": str(value)}))
    return matches


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        matches = iter_candidate_records(payload)
        return [{**record, "_record_path": record_path} for record_path, record in matches]
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [{"text": line, "_record_path": f"line:{index + 1}"} for index, line in enumerate(lines)]


def canonical_author(raw_author: str | None) -> str | None:
    if not raw_author:
        return None
    author = raw_author.strip()
    if not author:
        return None
    return author if author.startswith("@") else f"@{author}"


def extract_text(record: dict[str, Any]) -> str:
    parts: list[str] = []
    lowered = {normalize_key(key): value for key, value in record.items()}
    for key in TEXT_KEYS:
        parts.extend(nested_strings(lowered.get(key)))
    return " ".join(part for part in parts if part).strip()


def extract_urls(record: dict[str, Any], text: str) -> list[str]:
    urls = set(URL_RE.findall(text))
    lowered = {normalize_key(key): value for key, value in record.items()}
    for key in URL_KEYS:
        for candidate in nested_strings(lowered.get(key)):
            if candidate.startswith("http://") or candidate.startswith("https://"):
                urls.add(candidate)
    return sorted(urls)


def domain_for(value: str) -> str | None:
    if "@" in value and not value.startswith("http"):
        return value.rsplit("@", 1)[-1].lower()
    parsed = urlparse(value)
    if parsed.netloc:
        return parsed.netloc.lower()
    return None


def sentiment_for(text: str) -> dict[str, Any]:
    words = [word.lower() for word in WORD_RE.findall(text)]
    if not words:
        return {"label": "neutral", "score": 0.0, "positive": 0, "negative": 0}
    positive = sum(1 for word in words if word in POSITIVE_WORDS)
    negative = sum(1 for word in words if word in NEGATIVE_WORDS)
    score = round((positive - negative) / len(words), 4)
    if score > 0.05:
        label = "positive"
    elif score < -0.05:
        label = "negative"
    else:
        label = "neutral"
    return {"label": label, "score": score, "positive": positive, "negative": negative}


def parse_timestamp(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    value = raw_value.strip()
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def top_counter(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    return [{"value": value, "count": count} for value, count in counter.most_common(limit)]


def build_graph(records: list[dict[str, Any]]) -> dict[str, Any]:
    node_types: dict[str, str] = {}
    edges: Counter[tuple[str, str, str]] = Counter()

    def register_node(node_id: str, node_type: str) -> None:
        if node_id and node_id not in node_types:
            node_types[node_id] = node_type

    for record in records:
        author = record["author"]
        if author:
            register_node(author, "account")
        for mention in record["mentions"]:
            target = f"@{mention}" if not mention.startswith("@") else mention
            register_node(target, "account")
            if author:
                edges[(author, target, "mentions")] += 1
        for domain in record["domains"]:
            node = f"domain:{domain}"
            register_node(node, "domain")
            if author:
                edges[(author, node, "shares")] += 1
        for hashtag in record["hashtags"]:
            node = f"#{hashtag}"
            register_node(node, "hashtag")
            if author:
                edges[(author, node, "tags")] += 1
        for email in record["emails"]:
            node = f"email:{email.lower()}"
            register_node(node, "email")
            if author:
                edges[(author, node, "uses")] += 1

    graph_nodes = [{"id": node_id, "type": node_type} for node_id, node_type in sorted(node_types.items())]
    graph_edges = [
        {"source": source, "target": target, "relation": relation, "weight": weight}
        for (source, target, relation), weight in edges.most_common(50)
    ]
    return {
        "nodes": graph_nodes,
        "edges": graph_edges,
        "mermaid": render_mermaid(graph_edges),
    }


def render_mermaid(edges: list[dict[str, Any]]) -> str:
    def safe_label(value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace("\n", " ")
            .replace("\r", " ")
            .replace('"', "'")
        )

    lines = ["graph TD"]
    for edge in edges[:40]:
        source = safe_label(edge["source"])
        target = safe_label(edge["target"])
        relation = safe_label(edge["relation"])
        weight = edge["weight"]
        lines.append(f'    "{source}" -- "{relation} ({weight})" --> "{target}"')
    return "\n".join(lines)


def summarize_scraped(records: list[dict[str, Any]]) -> dict[str, Any]:
    domain_counts: Counter[str] = Counter()
    platform_counts: Counter[str] = Counter()
    urls = 0
    for record in records:
        domain_counts.update(record["domains"])
        if record["platform"]:
            platform_counts.update([record["platform"]])
        urls += len(record["urls"])
    return {
        "records": len(records),
        "records_with_urls": sum(1 for record in records if record["urls"]),
        "urls_detected": urls,
        "top_domains": top_counter(domain_counts),
        "platforms": top_counter(platform_counts),
    }


def summarize_socint(records: list[dict[str, Any]]) -> dict[str, Any]:
    emails: Counter[str] = Counter()
    phones: Counter[str] = Counter()
    mentions: Counter[str] = Counter()
    hashtags: Counter[str] = Counter()
    accounts: Counter[str] = Counter()
    domains: Counter[str] = Counter()

    for record in records:
        emails.update(email.lower() for email in record["emails"])
        phones.update(record["phones"])
        mentions.update(mention.lower() for mention in record["mentions"])
        hashtags.update(tag.lower() for tag in record["hashtags"])
        domains.update(record["domains"])
        if record["author"]:
            accounts.update([record["author"].lower()])

    return {
        "accounts": top_counter(accounts),
        "emails": top_counter(emails),
        "phones": top_counter(phones),
        "mentions": top_counter(mentions),
        "hashtags": top_counter(hashtags),
        "domains": top_counter(domains),
        "unique_accounts": len(accounts),
        "unique_emails": len(emails),
        "unique_phones": len(phones),
    }


def summarize_socmint(records: list[dict[str, Any]]) -> dict[str, Any]:
    account_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "posts": 0,
            "platforms": Counter(),
            "hashtags": Counter(),
            "mentions": Counter(),
            "domains": Counter(),
            "sentiment_total": 0.0,
        }
    )
    hourly_activity: Counter[str] = Counter()
    for record in records:
        author = record["author"]
        parsed_timestamp = parse_timestamp(record["timestamp"])
        if parsed_timestamp:
            hourly_activity.update([f"{parsed_timestamp.hour:02d}:00"])
        if not author:
            continue
        stats = account_stats[author]
        stats["posts"] += 1
        if record["platform"]:
            stats["platforms"].update([record["platform"]])
        stats["hashtags"].update(tag.lower() for tag in record["hashtags"])
        stats["mentions"].update(mention.lower() for mention in record["mentions"])
        stats["domains"].update(record["domains"])
        stats["sentiment_total"] += record["sentiment"]["score"]

    accounts = []
    for author, stats in sorted(account_stats.items(), key=lambda item: item[1]["posts"], reverse=True)[:15]:
        posts = stats["posts"] or 1
        accounts.append(
            {
                "account": author,
                "posts": stats["posts"],
                "average_sentiment": round(stats["sentiment_total"] / posts, 4),
                "platforms": top_counter(stats["platforms"], limit=5),
                "top_hashtags": top_counter(stats["hashtags"], limit=5),
                "top_mentions": top_counter(stats["mentions"], limit=5),
                "top_domains": top_counter(stats["domains"], limit=5),
            }
        )

    return {
        "accounts": accounts,
        "activity_by_hour_utc": top_counter(hourly_activity, limit=24),
        "tracked_accounts": len(account_stats),
    }


def summarize_breaches(records: list[dict[str, Any]]) -> dict[str, Any]:
    exposures: dict[str, Counter[str]] = {name: Counter() for name in BREACH_PATTERNS}
    flagged_records = []
    risk_score = 0
    for record in records:
        text = record["text"]
        record_hits: dict[str, int] = {}
        for name, pattern in BREACH_PATTERNS.items():
            matches = [match.group(0) for match in pattern.finditer(text)]
            if not matches:
                continue
            exposures[name].update(matches)
            record_hits[name] = len(matches)
        if record_hits:
            risk_score += sum(record_hits.values())
            flagged_records.append(
                {
                    "record_path": record["record_path"],
                    "author": record["author"],
                    "platform": record["platform"],
                    "hits": record_hits,
                }
            )

    if risk_score >= 20:
        severity = "critical"
    elif risk_score >= 10:
        severity = "high"
    elif risk_score >= 4:
        severity = "medium"
    else:
        severity = "low"

    return {
        "severity": severity,
        "risk_score": risk_score,
        "flagged_records": flagged_records[:25],
        "indicator_counts": {name: sum(counter.values()) for name, counter in exposures.items() if counter},
        "top_indicators": {
            name: top_counter(counter, limit=5)
            for name, counter in exposures.items()
            if counter
        },
    }


def summarize_sentiment(records: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(record["sentiment"]["label"] for record in records)
    scores = [record["sentiment"]["score"] for record in records]
    return {
        "distribution": top_counter(labels, limit=3),
        "average_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "most_positive": [
            {"record_path": record["record_path"], "author": record["author"], "score": record["sentiment"]["score"], "text": record["text"][:180]}
            for record in sorted(records, key=lambda item: item["sentiment"]["score"], reverse=True)[:5]
        ],
        "most_negative": [
            {"record_path": record["record_path"], "author": record["author"], "score": record["sentiment"]["score"], "text": record["text"][:180]}
            for record in sorted(records, key=lambda item: item["sentiment"]["score"])[:5]
        ],
    }


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    text = extract_text(record)
    author = canonical_author(pick_first_string(record, AUTHOR_KEYS))
    platform = pick_first_string(record, PLATFORM_KEYS)
    timestamp = pick_first_string(record, TIMESTAMP_KEYS)
    urls = extract_urls(record, text)
    emails = sorted({email.lower() for email in EMAIL_RE.findall(text)})
    phones = sorted({phone.strip() for phone in PHONE_RE.findall(text)})
    mentions = sorted({mention.lower() for mention in MENTION_RE.findall(text)})
    hashtags = sorted({tag.lower() for tag in HASHTAG_RE.findall(text)})
    domains = sorted({domain for domain in (domain_for(value) for value in urls + emails) if domain})
    sentiment = sentiment_for(text)
    return {
        "record_path": str(record.get("_record_path", "root")),
        "text": text,
        "author": author,
        "platform": platform,
        "timestamp": timestamp,
        "urls": urls,
        "emails": emails,
        "phones": phones,
        "mentions": mentions,
        "hashtags": hashtags,
        "domains": domains,
        "sentiment": sentiment,
    }


def analyze(path: Path) -> dict[str, Any]:
    normalized_records = [normalize_record(record) for record in load_records(path)]
    normalized_records = [record for record in normalized_records if record["text"]]
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceFile": str(path),
        "summary": {
            "records": len(normalized_records),
            "accounts": len({record["author"] for record in normalized_records if record["author"]}),
            "platforms": len({record["platform"] for record in normalized_records if record["platform"]}),
            "domains": len({domain for record in normalized_records for domain in record["domains"]}),
        },
        "socint": summarize_socint(normalized_records),
        "socmint": summarize_socmint(normalized_records),
        "scraped": summarize_scraped(normalized_records),
        "leaks_and_breaches": summarize_breaches(normalized_records),
        "sentiment_analysis": summarize_sentiment(normalized_records),
        "graphs": build_graph(normalized_records),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze existing scraped/social intelligence datasets for SOCINT, SOCMINT, leaks/breaches, sentiment, and entity graphs."
    )
    parser.add_argument("input", type=Path, help="Path to a JSON dataset or plain text file")
    parser.add_argument("-o", "--output", type=Path, help="Write the analysis JSON to this file")
    parser.add_argument(
        "--graph-format",
        choices=("json", "mermaid", "both"),
        default="both",
        help="Control the graph payload in the output",
    )
    args = parser.parse_args()

    result = analyze(args.input.expanduser())
    if args.graph_format == "json":
        result["graphs"].pop("mermaid", None)
    elif args.graph_format == "mermaid":
        result["graphs"] = {"mermaid": result["graphs"]["mermaid"]}

    if args.output:
        output_path = args.output.expanduser()
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Analyzed {result['summary']['records']} records and wrote {output_path}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
