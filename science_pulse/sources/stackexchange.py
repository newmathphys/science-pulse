from __future__ import annotations

import html
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ..models import Post, make_id
from ..text import clean_text, truncate
from .base import Source, SourceError

LOGGER = logging.getLogger(__name__)

QUESTIONS_URL = "https://api.stackexchange.com/2.3/questions"
ANSWERS_URL = "https://api.stackexchange.com/2.3/answers/{ids}"
LATEX_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$|\\\[(.+?)\\\]|\\\((.+?)\\\)", re.DOTALL)

DEFAULT_SITES: Dict[str, List[Tuple[str, str]]] = {
    "math": [("math", "calculus"), ("math", "linear-algebra"), ("math", "number-theory")],
    "physics": [("physics", "quantum-mechanics"), ("physics", "classical-mechanics")],
    "cs": [("cs", "algorithms"), ("cstheory", "complexity-theory"), ("scicomp", "differential-equations")],
}


class StackExchangeSource(Source):
    name = "stackexchange"
    domains = ("math", "physics", "cs")
    tier = "online"

    def fetch(self, limit: int = 2, cycle: int = 0) -> List[Post]:
        domains = list(self.config.domains)
        if not domains:
            return []
        domain = domains[cycle % len(domains)]
        options = self.config.source_options(self.name)
        configured = options.get("sites") or DEFAULT_SITES
        pairs = configured.get(domain) or DEFAULT_SITES.get(domain, [])
        if not pairs:
            return []

        site, tag = pairs[cycle % len(pairs)]
        try:
            questions = self._fetch_questions(site, tag, max(limit * 3, 6))
            accepted = {
                int(item["accepted_answer_id"]): item
                for item in questions
                if item.get("accepted_answer_id")
            }
            if not accepted:
                LOGGER.info("StackExchange %s/%s: нет вопросов с accepted_answer_id", site, tag)
                return []
            answers = self._fetch_answers(site, list(accepted)[:10])
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError(f"StackExchange {site}/{tag}: {exc}") from exc

        return self.build_posts(accepted, answers, domain, site)[:limit]

    def _fetch_questions(self, site: str, tag: str, pagesize: int) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "order": "desc",
            "sort": "votes",
            "min": 20,
            "tagged": tag,
            "site": site,
            "pagesize": min(pagesize, 30),
        }
        key = self.config.raw.get("stackexchange_key") or ""
        if key:
            params["key"] = key
        data = self.http.get_json(QUESTIONS_URL, params=params)
        if not isinstance(data, dict):
            raise SourceError("StackExchange: неожиданный формат questions")
        backoff = data.get("backoff")
        if backoff:
            LOGGER.warning("StackExchange просит backoff=%s секунд", backoff)
        return list(data.get("items") or [])

    def _fetch_answers(self, site: str, ids: List[int]) -> List[Dict[str, Any]]:
        if not ids:
            return []
        params: Dict[str, Any] = {
            "site": site,
            "filter": "withbody",
            "order": "desc",
            "sort": "votes",
            "pagesize": min(len(ids), 30),
        }
        key = self.config.raw.get("stackexchange_key") or ""
        if key:
            params["key"] = key
        data = self.http.get_json(ANSWERS_URL.format(ids=";".join(map(str, ids))), params=params)
        if not isinstance(data, dict):
            raise SourceError("StackExchange: неожиданный формат answers")
        return list(data.get("items") or [])

    @staticmethod
    def extract_formulas(body_html: str) -> List[str]:
        text = html.unescape(body_html or "")
        found: List[str] = []
        for match in LATEX_RE.finditer(text):
            formula = next((group for group in match.groups() if group), "")
            formula = re.sub(r"\s+", " ", formula).strip()
            if not (5 <= len(formula) <= 220):
                continue
            if not any(marker in formula for marker in ("=", "\\frac", "\\sum", "\\int", "^", "\\sqrt")):
                continue
            if formula not in found:
                found.append(formula)
        return found

    def build_posts(
        self,
        questions_by_answer: Dict[int, Dict[str, Any]],
        answers: List[Dict[str, Any]],
        domain: str,
        site: str,
    ) -> List[Post]:
        posts: List[Post] = []
        for answer in answers:
            try:
                answer_id = int(answer.get("answer_id"))
            except (TypeError, ValueError):
                continue
            question = questions_by_answer.get(answer_id)
            if not question:
                continue
            if int(answer.get("score") or 0) < 10:
                continue

            raw_title = html.unescape(question.get("title") or "")
            raw_body = html.unescape(answer.get("body") or "")
            formulas = self.extract_formulas(raw_body)
            if not formulas:
                continue

            title = self._translate(truncate(raw_title, 180))
            body_text = clean_text(raw_body, max_len=900)
            body_text = self._translate(body_text)
            if len(body_text) < 80:
                continue

            post = Post(
                id=make_id(self.name, f"{site}:{answer_id}"),
                domain=domain,
                title=title,
                hook=truncate(title, 140),
                body=body_text,
                formula_latex=formulas[0],
                formula_plain=formulas[0],
                source_name=f"Stack Exchange / {site}",
                source_url=f"https://{site}.stackexchange.com/a/{answer_id}",
                tier=self.tier,
                meta={
                    "question_id": question.get("question_id"),
                    "answer_id": answer_id,
                    "question_score": question.get("score", 0),
                    "answer_score": answer.get("score", 0),
                    "views": question.get("view_count", 0),
                    "site": site,
                },
            )
            post.quality = post.quality_score()
            posts.append(post)

        posts.sort(key=lambda item: item.meta.get("answer_score", 0), reverse=True)
        return posts
