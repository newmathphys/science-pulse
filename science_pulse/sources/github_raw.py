from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from ..models import Post, make_id
from ..text import clean_text, smart_sentence_truncate, truncate
from .base import Source, SourceError


class GitHubRawSource(Source):
    name = "github_raw"
    domains = ("math", "physics", "cs")
    tier = "online"

    def fetch(self, limit: int = 2, cycle: int = 0) -> List[Post]:
        options = self.config.source_options(self.name)
        entries = options.get("urls") or []
        if not entries:
            return []
        posts: List[Post] = []
        for offset in range(min(max(limit, 1), len(entries))):
            entry = entries[(cycle + offset) % len(entries)]
            try:
                post = self.fetch_entry(entry)
            except SourceError:
                if not posts and offset == min(max(limit, 1), len(entries)) - 1:
                    raise
                continue
            if post:
                posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    def fetch_entry(self, entry: Dict[str, Any]) -> Post | None:
        url = entry.get("url", "")
        if not url.startswith(("http://", "https://")):
            return None
        raw = self.http.get_text(url)
        if len(raw) < 80:
            return None

        if url.endswith(".json") or raw.lstrip().startswith(("{", "[")):
            parsed = self._parse_json(raw)
        else:
            parsed = self._parse_markdown(raw)

        title = self._translate(parsed["title"])
        body = self._translate(parsed["body"])
        if len(title) < 8 or (len(body) < 80 and not parsed["code"]):
            return None

        post = Post(
            id=make_id(self.name, f"{url}:{title}"),
            domain=entry.get("domain", "math"),
            title=truncate(title, 200),
            hook=self._translate(parsed["hook"] or smart_sentence_truncate(body, 80, 180)),
            body=body,
            formula_latex=parsed["formula"],
            formula_plain=parsed["formula"],
            code=truncate(parsed["code"], 700),
            source_name="GitHub raw",
            source_url=url,
            tier=self.tier,
            meta={"raw_url": url},
        )
        post.quality = post.quality_score()
        return post

    @staticmethod
    def _parse_markdown(raw: str) -> Dict[str, str]:
        lines = raw.splitlines()
        title = ""
        for line in lines:
            match = re.match(r"^#\s+(.+)$", line.strip())
            if match:
                title = match.group(1).strip()
                break
        if not title:
            title = next((line.strip("# ").strip() for line in lines if line.strip()), "GitHub материал")

        code_match = re.search(r"```[a-zA-Z0-9_+-]*\n(.*?)```", raw, re.DOTALL)
        code = code_match.group(1).strip() if code_match else ""

        body_lines: List[str] = []
        in_code = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                continue
            if in_code or stripped.startswith("#") or stripped.startswith("!["):
                continue
            if stripped.startswith(("- ", "* ", "|", ">")):
                stripped = re.sub(r"^[-*>\s]+", "", stripped)
            if stripped:
                body_lines.append(stripped)
            if len(" ".join(body_lines)) > 1200:
                break
        body = clean_text(" ".join(body_lines), max_len=1000)

        formula_match = re.search(r"\$\$(.+?)\$\$|\$(.+?)\$", raw, re.DOTALL)
        formula = ""
        if formula_match:
            formula = next((g for g in formula_match.groups() if g), "").strip()
            formula = truncate(formula, 180)

        return {
            "title": title,
            "hook": truncate(body, 150),
            "body": body,
            "code": code,
            "formula": formula,
        }

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, str]:
        try:
            data = json.loads(raw)
        except ValueError:
            return {"title": "JSON материал", "hook": "", "body": clean_text(raw, max_len=900), "code": "", "formula": ""}
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            return {"title": "JSON материал", "hook": "", "body": clean_text(raw, max_len=900), "code": "", "formula": ""}

        title = str(data.get("title") or data.get("name") or data.get("term") or "JSON материал")
        body = str(
            data.get("text")
            or data.get("body")
            or data.get("description")
            or data.get("fact")
            or data.get("explanation")
            or ""
        )
        formula = str(data.get("formula") or data.get("equation") or "")
        code = str(data.get("code") or data.get("example") or "")
        return {
            "title": title,
            "hook": truncate(clean_text(body, max_len=150), 150),
            "body": clean_text(body, max_len=1000),
            "code": code,
            "formula": truncate(formula, 180),
        }
