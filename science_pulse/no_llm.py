"""Аудит «в контенте нет LLM».

Проверяет не декларации, а исходники: в пакете ``science_pulse`` не должно
быть импортов LLM- SDK, вызовов генеративных API и адресов моделей. Перевод
(если владелец включит ``SP_TRANSLATE=1``) идёт через не-генеративные
эшелоны gtx/MyMemory и по умолчанию выключен.

Аудит встроен в ``cli verify``: ``./sp check`` доказывает отсутствие LLM
каждый прогон, а не только обещает его в README.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List

FORBIDDEN_MODULES = {
    "openai",
    "anthropic",
    "google.generativeai",
    "google.genai",
    "ollama",
    "llama_index",
    "langchain",
    "langchain_core",
    "transformers",
    "torch",
    "tensorflow",
    "huggingface_hub",
    "cohere",
    "mistralai",
    "gigachat",
    "yandexgpt",
    "deepseek",
    "vllm",
    "litellm",
    "openrouter",
    "replicate",
}

FORBIDDEN_HOSTS = (
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.deepseek.com",
    "api.mistral.ai",
    "api.cohere.ai",
    "openrouter.ai",
    "api.replicate.com",
    "localhost:11434",
    "127.0.0.1:11434",
)

FORBIDDEN_CALLS = (
    "chat.completions.create",
    "responses.create",
    "generate_content",
    "ChatCompletion.create",
)


def _imports(tree: ast.AST) -> List[str]:
    names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _matches(name: str, forbidden: set[str]) -> bool:
    return any(name == item or name.startswith(item + ".") for item in forbidden)


def scan_source(path: Path) -> List[str]:
    """Нарушения в одном файле: импорты, адреса, генеративные вызовы."""
    text = path.read_text(encoding="utf-8", errors="replace")
    violations: List[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [f"{path}: синтаксис: {exc}"]

    for name in _imports(tree):
        if _matches(name, FORBIDDEN_MODULES):
            violations.append(f"{path}: импорт LLM-модуля {name}")

    for host in FORBIDDEN_HOSTS:
        if host in text:
            violations.append(f"{path}: адрес LLM-API {host}")

    for call in FORBIDDEN_CALLS:
        if call in text:
            violations.append(f"{path}: вызов генеративного API {call}")

    return violations


def audit_no_llm(root: Path | None = None) -> Dict[str, Any]:
    """Сканирует пакет и возвращает отчёт для ``verify``."""
    package = root or Path(__file__).resolve().parent
    files = sorted(
        path
        for path in package.rglob("*.py")
        if "__pycache__" not in path.parts and path.name != "no_llm.py"
    )
    violations: List[str] = []
    for path in files:
        violations.extend(scan_source(path))
    return {
        "ok": not violations,
        "files": len(files),
        "violations": violations[:10],
    }


def format_audit(report: Dict[str, Any]) -> str:
    if report["ok"]:
        return f"{report['files']} файлов · LLM-импортов и API нет"
    return f"нарушений {len(report['violations'])}: " + "; ".join(report["violations"])
