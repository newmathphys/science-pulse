from __future__ import annotations

from typing import List

from ..models import Post, make_id
from ..text import clean_text, smart_sentence_truncate, truncate
from .base import Source, SourceError


class NumbersSource(Source):
    name = "numbers"
    domains = ("math",)
    tier = "online"

    def fetch(self, limit: int = 1, cycle: int = 0) -> List[Post]:
        posts: List[Post] = []
        for _ in range(max(1, min(limit, 2))):
            try:
                data = self.http.get_json("http://numbersapi.com/random/math?json")
            except SourceError:
                if posts:
                    break
                raise
            text = clean_text(str(data.get("text") or ""), max_len=500)
            number = data.get("number")
            if not text or number is None:
                continue
            post = Post(
                id=make_id(self.name, f"{number}:{text[:40]}"),
                domain="math",
                title=self._translate(f"Математический факт о числе {number}"),
                hook=self._translate(smart_sentence_truncate(text, 80, 180)),
                body=self._translate(text),
                source_name="Numbers API",
                source_url=f"http://numbersapi.com/{number}/math",
                tier=self.tier,
                meta={"number": number},
            )
            post.quality = post.quality_score()
            posts.append(post)
        return posts
