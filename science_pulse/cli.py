from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .config import load_config
from .pipeline import Pipeline
from .storage import Storage

LOGGER = logging.getLogger("science_pulse")


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _pipeline(args: argparse.Namespace) -> Pipeline:
    config = load_config(args.config, root=args.root)
    return Pipeline(config)


def _checkpoint(pipeline: Pipeline) -> None:
    try:
        pipeline.storage.checkpoint()
    except Exception as exc:
        LOGGER.warning("WAL checkpoint не удался: %s", exc)


def _print_status(status: dict) -> None:
    print(f"Очередь:      {status['ready']}")
    print(f"Опубликовано: {status['published']}")
    print(f"Ошибок:       {status['failed']}")
    print(f"Пауза:        {'да' if status['paused'] else 'нет'}")
    print("По дисциплинам: " + ", ".join(f"{key}={value}" for key, value in status["by_domain"].items()))
    last = status.get("last")
    if last:
        print(f"Последний:    {last.get('title')} [{last.get('domain')}]")
    print("Площадки:")
    for item in status.get("platforms", []):
        print(f"  {item['name']}: {'готов' if item['available'] else 'нет токенов'}")
    print("Источники:")
    for item in status.get("sources", []):
        state = "OPEN" if item["open"] else "ok"
        print(f"  {item['name']}: {state}, ошибок {item['failures']}")


def cmd_init(args: argparse.Namespace) -> int:
    config = load_config(args.config, root=args.root)
    config.ensure_dirs()
    storage = Storage(config.db_path)
    try:
        from .knowledge import KnowledgeBase, format_stats

        knowledge = KnowledgeBase(config.data_dir / "knowledge.db", root=config.root)
        result = knowledge.index_documents(config.root)
        print(f"Knowledge: {result['indexed']} новых, {result['skipped']} без изменений")
    except Exception as exc:
        print(f"Knowledge: пропущено ({exc})")
    print(f"Инициализировано: {config.root}")
    print(f"База: {config.db_path}")
    print(f"Карточки: {config.cards_dir}")
    print(f"Сайт: {config.dist_dir}")
    print(f"Постов в базе: {storage.count()}")
    return 0


def cmd_knowledge(args: argparse.Namespace) -> int:
    """SCM Knowledge Base: индексация документов, поиск, утверждения, integrity."""
    from .knowledge import KnowledgeBase, format_search, format_stats

    config = load_config(args.config, root=args.root)
    config.ensure_dirs()
    kb = KnowledgeBase(config.data_dir / "knowledge.db", root=config.root)
    action = args.action
    if action == "index":
        result = kb.index_documents(config.root)
        print(f"Индекс: {result['indexed']} новых, {result['skipped']} без изменений, всего {result['total']}")
        return 0
    if action == "search":
        rows = kb.search(args.value or "", limit=args.limit)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print(format_search(rows))
        return 0
    if action == "stats":
        stats = kb.stats()
        print(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2) if args.json else format_stats(stats))
        return 0
    if action == "claim":
        if args.value:
            claim_id = kb.add_claim(args.value, status=args.status, source=args.source)
            print(f"Утверждение #{claim_id}: {args.status} (owner_signed=0)")
        else:
            rows = kb.list_claims(limit=args.limit)
            print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else "\n".join(
                f"#{row['id']} [{row['status']}] {row['text']} — {row['source']}" for row in rows
            ) or "Утверждений нет.")
        return 0
    if action == "note":
        if args.value:
            note_id = kb.add_note(args.value, source=args.source, status=args.status)
            print(f"Заметка #{note_id}: {args.status} (owner_signed=0)")
        else:
            rows = kb.list_notes(limit=args.limit)
            print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else "\n".join(
                f"#{row['id']} [{row['status']}] {row['text']} — {row['source']}" for row in rows
            ) or "Заметок нет.")
        return 0
    if action == "decisions":
        rows = kb.list_decisions(limit=args.limit)
        print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else "\n".join(
            f"#{row['id']} {row['title']}: {row['decision']}" for row in rows
        ) or "Решений нет.")
        return 0
    if action == "integrity":
        report = kb.integrity()
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else (
            "✅ Knowledge Base целостна" if report["ok"] else "❌ " + "; ".join(report["issues"])
        ))
        return 0 if report["ok"] else 1
    if action == "export":
        path = kb.export_json(config.data_dir / "knowledge_export.json")
        print(f"Экспорт: {path}")
        return 0
    print("Действия: index|search|stats|claim|note|decisions|integrity|export")
    return 1


def cmd_status(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    status = pipeline.status()
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
    else:
        _print_status(status)
    return 0


def cmd_harvest(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    domains = [args.domain] if args.domain else None
    added = pipeline.harvest(limit_per_source=args.limit, domains=domains, include_offline=args.offline)
    _checkpoint(pipeline)
    print(f"Добавлено: {added}. Очередь: {pipeline.storage.count('ready')}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    result = pipeline.publish_next(
        dry_run=args.dry_run,
        domain=args.domain,
        targets=args.target or None,
        force=args.force,
        build_site=not args.no_site,
        post_id=args.post_id,
        video=True if getattr(args, "video", False) else (False if getattr(args, "no_video", False) else None),
    )
    if result.get("deferred"):
        _checkpoint(pipeline)
        print(f"Публикация отложена ({result.get('reason')}): {result.get('error')}")
        return 0
    if not result.get("ok"):
        _checkpoint(pipeline)
        print(f"Не опубликовано: {result.get('error')}", file=sys.stderr)
        return 1
    post = result["post"]
    print(f"Пост: {post.title} [{post.domain}]")
    print(f"Карточка: {result['card'].path}")
    if result.get("dry_run"):
        print("Режим dry-run: в сеть не отправлялось.")
    for item in result.get("results", []):
        state = "skipped" if item.get("skipped") else ("ok" if item.get("ok") else "error")
        print(f"  {item['platform']}: {state} {item.get('url') or item.get('error') or ''}")
    _checkpoint(pipeline)
    return 0


def cmd_post(args: argparse.Namespace) -> int:
    """Единый предпросмотр поста: карточка + подпись + детальное описание.

    Ничего не публикует в соцсети. С ``--send`` отправляет карточку с подписью
    в админ-чат Telegram (тот же, что у пульта) — удобно для эталонных постов.
    """
    import requests

    from .cards import render_card
    from .publishers.base import build_caption, build_full_description

    pipeline = _pipeline(args)
    storage, config = pipeline.storage, pipeline.config
    post = storage.get_post(args.id) if args.id else pipeline.choose_next(domain=args.domain)
    if post is None:
        print("Пост не найден", file=sys.stderr)
        return 1

    out_path = Path(config.cards_dir) / f"{post.id}.png"
    card = render_card(post, out_path=out_path, engine=args.engine)
    caption = build_caption(post, limit=1020, html=True, site_url=config.site_base_url)
    description = build_full_description(post, site_url=config.site_base_url)
    print(f"Пост: {post.title} [{post.domain}] · {post.status}")
    print(f"Карточка: {card.path}")
    print(f"\n--- ПОДПИСЬ ({len(caption)} симв.) ---\n{caption}")
    print(f"\n--- ОПИСАНИЕ ({len(description)} симв.) ---\n{description}")

    if args.send:
        if not (config.telegram_token and config.telegram_admin_chat):
            print("Нет TG_BOT_TOKEN/TG_ADMIN_CHAT_ID — отправка невозможна", file=sys.stderr)
            return 1
        api = f"https://api.telegram.org/bot{config.telegram_token}"
        response = requests.post(
            f"{api}/sendPhoto",
            data={
                "chat_id": config.telegram_admin_chat,
                "caption": caption[:1020],
                "parse_mode": "HTML",
            },
            files={"photo": ("card.png", card.data, "image/png")},
            timeout=30,
        )
        payload = response.json()
        if not payload.get("ok"):
            print(f"Telegram: {payload.get('description')}", file=sys.stderr)
            return 1
        print(f"Отправлено в админ-чат: message_id {payload['result']['message_id']}")
    _checkpoint(pipeline)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    result = pipeline.run(
        dry_run=args.dry_run,
        harvest_if_low=not args.no_harvest,
        build_site=not args.no_site,
    )
    if result.get("deferred"):
        _checkpoint(pipeline)
        print(f"Публикация отложена ({result.get('reason')}): {result.get('error')}")
        return 0
    if not result.get("ok"):
        _checkpoint(pipeline)
        print(f"Запуск не удался: {result.get('error')}", file=sys.stderr)
        return 1
    post = result["post"]
    print(f"Готово: {post.title} [{post.domain}]")
    print(f"Карточка: {result['card'].path}")
    for item in result.get("results", []):
        state = "skipped" if item.get("skipped") else ("ok" if item.get("ok") else "error")
        print(f"  {item['platform']}: {state} {item.get('url') or item.get('error') or ''}")
    _checkpoint(pipeline)
    return 0


def cmd_site(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    path = pipeline.build_site()
    _checkpoint(pipeline)
    print(f"Сайт собран: {path}")
    return 0


def cmd_radio(args: argparse.Namespace) -> int:
    """Веб-радиостанция: сборка страницы, подкаста, микса и RTMP-вещание."""
    from .radio import build_radio_mix, mix_plan, radio_status, rtmp_argv, write_chapters, write_radio

    pipeline = _pipeline(args)
    posts = pipeline.storage.list_posts(limit=2000)
    if args.rtmp:
        source = pipeline.config.dist_dir / "radio_mix.mp4"
        if not source.is_file():
            print("Сначала соберите микс: cli radio --mix", file=sys.stderr)
            return 1
        argv = rtmp_argv(args.rtmp, source)
        print("Вещание: " + " ".join(argv))
        if args.run:
            return subprocess.call(argv)
        return 0
    if args.mix:
        out = pipeline.config.dist_dir / "radio_mix.mp4"
        chapters = pipeline.config.dist_dir / "radio_chapters.txt"
        result = build_radio_mix(posts, pipeline.config.data_dir, out, chapters)
        if result is None:
            print("Микс не собран: нужен ffmpeg и хотя бы одна видео-аудиограмма.", file=sys.stderr)
            return 1
        print(f"Радио-микс: {result}")
        if chapters.is_file():
            print(f"Таймкоды:   {chapters}")
        _checkpoint(pipeline)
        return 0
    status = radio_status(posts, pipeline.config)
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0
    written = write_radio(pipeline.config.dist_dir, posts, pipeline.config)
    plan = mix_plan(posts, pipeline.config.data_dir)
    print(f"📻 {status['episodes']} выпусков (с озвучкой {status['with_audio']})")
    print(f"Такт эпохи: № {status['slot']} · в эфире: {status['now'] or '—'}")
    print(f"Страница:   {written['radio']}")
    print(f"Подкаст:    {written['podcast']}")
    print(f"Готово к миксу: {len(plan['chapters'])} видео-аудиограмм, ~{plan['total_seconds']:.0f} с")
    _checkpoint(pipeline)
    return 0


def cmd_kernel(args: argparse.Namespace) -> int:
    """Центральное детерминированное ядро: паспорт состояния или полный цикл."""
    from .kernel import SciencePulseKernel

    pipeline = _pipeline(args)
    kernel = SciencePulseKernel(pipeline.config, pipeline.storage, pipeline)
    if args.tick:
        report = kernel.run_cycle(
            expand=not args.no_expand,
            expand_count=args.count,
            publish=args.publish,
            voice=args.voice,
            rebuild_site=not args.no_site,
            formal=args.formal,
            deep=getattr(args, "deep", False),
            deep_depth=getattr(args, "depth", 1),
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        for name, payload in report.items():
            mark = "✅" if payload.get("ok") else "⚠️"
            print(f"{mark} {name}: {json.dumps(payload, ensure_ascii=False)[:200]}")
        _checkpoint(pipeline)
        return 0
    report = kernel.status_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(kernel.format_status(report))
    _checkpoint(pipeline)
    return 0


def cmd_expand(args: argparse.Namespace) -> int:
    """Бесконечный насос: добрать темы курса (и, при --deep, мета-каталогов)."""
    from .kernel import SciencePulseKernel

    pipeline = _pipeline(args)
    kernel = SciencePulseKernel(pipeline.config, pipeline.storage, pipeline)
    result = kernel.expand_syllabus(count=args.count)
    deep: Dict[str, Any] = {}
    if getattr(args, "deep", False):
        deep = kernel.expand_deep(count=args.count, depth=getattr(args, "depth", 1))
    if args.json:
        print(json.dumps({**result, **deep}, ensure_ascii=False, indent=2))
        return 0
    print(
        f"Добавлено тем курса: {result['syllabus_added']} · "
        f"в очереди ready: {result['ready']} · курсор: {result['cursor']}"
    )
    if deep:
        if deep.get("reason"):
            print(f"Глубокий обход: {deep['reason']}")
        else:
            print(
                f"Глубокий обход (глубина {deep.get('depth')}): добавлено {deep.get('deep_added')} "
                f"из {deep.get('deep_seen')} найденных тем · курсор {deep.get('deep_cursor')}"
            )
    _checkpoint(pipeline)
    return 0


def cmd_quiz(args: argparse.Namespace) -> int:
    """Нативная викторина: показать (или отправить) задачу-опрос следующего поста."""
    from .challenge import build_challenge, quiz_options

    pipeline = _pipeline(args)
    post = pipeline.choose_next(getattr(args, "domain", None))
    if post is None:
        print("Очередь пуста: нечего спрашивать.", file=sys.stderr)
        return 1
    challenge = build_challenge(post)
    quiz = quiz_options(challenge)
    if args.json:
        print(json.dumps({"post": post.id, "challenge": challenge, "quiz": quiz},
                         ensure_ascii=False, indent=2))
        return 0
    if not quiz:
        print(f"§ {(post.meta or {}).get('section_num', '')}: у задачи нет числового ответа — "
              "викторина не строится (варианты не выдумываем).")
        print(f"Вопрос: {challenge.get('question')}")
        return 0
    print(f"🧠 {post.title}")
    print(f"Вопрос: {quiz['question']}")
    for index, option in enumerate(quiz["options"]):
        mark = "✅" if index == quiz["correct_index"] else "  "
        print(f"  {mark} {option}")
    if args.send:
        result = pipeline.send_quiz_poll(post)
        if result:
            print(f"Викторина отправлена: message_id={result.get('message_id')}")
        else:
            print("Не отправлено: нет Telegram-токена/канала или викторина недоступна.",
                  file=sys.stderr)
            return 1
    _checkpoint(pipeline)
    return 0


def cmd_admin(args: argparse.Namespace) -> int:
    from .admin import TelegramAdmin

    pipeline = _pipeline(args)
    admin = TelegramAdmin(pipeline.config, pipeline)
    if not admin.available():
        print("Пульт недоступен: задайте TG_BOT_TOKEN и TG_ADMIN_CHAT_ID", file=sys.stderr)
        return 1
    if getattr(args, "once", False):
        handled = admin.poll_once(timeout=0)
        _checkpoint(pipeline)
        print(f"Обработано обновлений: {handled}")
        return 0
    admin.run_forever()
    _checkpoint(pipeline)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .admin import TelegramAdmin

    pipeline = _pipeline(args)
    admin = TelegramAdmin(pipeline.config, pipeline)
    report = admin._doctor_text()
    if args.send:
        if not admin.available():
            print("Не могу отправить: нужны TG_BOT_TOKEN и TG_ADMIN_CHAT_ID", file=sys.stderr)
            return 1
        admin.send(report)
        print("Отчёт /doctor отправлен в админ-чат.")
        return 0
    print(report)
    return 0


def cmd_growth(args: argparse.Namespace) -> int:
    """Рост аудитории: Threads-формат, UTM, реестр каналов."""
    from .growth import AudienceRegistry, ThreadsGrowthEngine, format_plan, format_report, format_targets, telegram_url, utm_url

    pipeline = _pipeline(args)
    registry = AudienceRegistry(pipeline.config.data_dir / "growth.db")
    action = args.action
    if action == "collect":
        from .audience import AudienceCollector

        snapshots = AudienceCollector(pipeline.config, pipeline.storage, registry).collect()
        print(json.dumps([item.as_dict() for item in snapshots], ensure_ascii=False, indent=2) if args.json else "\n".join(
            f"{item.platform}: {item.followers} подписчиков ({item.status}) {item.detail}" for item in snapshots
        ))
        return 0
    if action == "dashboard":
        from .audience import AudienceDashboard

        paths = AudienceDashboard(pipeline.config, pipeline.storage, registry).write()
        print(f"Growth report: {paths['markdown']}\nHTML: {paths['html']}")
        return 0
    if action == "plan":
        post = pipeline.storage.get_post(args.post_id) if args.post_id else pipeline.choose_next()
        if post is None:
            print("Нет поста для плана.", file=sys.stderr)
            return 1
        engine = ThreadsGrowthEngine(pipeline.config)
        plan = engine.plan(post, pipeline.config.site_base_url, telegram_url(pipeline.config))
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print(format_plan(plan))
        return 0
    if action == "targets":
        targets = registry.list(status=args.status, platform=args.platform, limit=args.limit)
        print(json.dumps([item.__dict__ for item in targets], ensure_ascii=False, indent=2) if args.json else format_targets(targets))
        return 0
    if action == "target-add":
        if not (args.platform and args.name and args.url):
            print("Нужны --platform, --name, --url", file=sys.stderr)
            return 2
        target_id = registry.add(args.platform, args.name, args.url, args.topic, args.audience, args.notes)
        print(f"Канал #{target_id}: {args.name} ({args.platform})")
        return 0
    if action == "report":
        report = registry.report()
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_report(report))
        return 0
    if action == "utm":
        print(utm_url(args.value or "", content=args.post_id or ""))
        return 0
    print("Действия: plan|targets|target-add|report|utm|collect|dashboard")
    return 1


def cmd_signal(args: argparse.Namespace) -> int:
    """Математический движок сигналов: объём, энтропия, УОС, интервалы."""
    from .signal_engine import format_signal_report, signal_status

    pipeline = _pipeline(args)
    status = signal_status(pipeline.storage, pipeline.config)
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_signal_report(pipeline.storage, pipeline.config, html=False))
    _checkpoint(pipeline)
    return 0


def cmd_trending(args: argparse.Namespace) -> int:
    from .trending import TrendingRadar, format_trending

    pipeline = _pipeline(args)
    radar = TrendingRadar(pipeline.config, pipeline.storage)
    items = radar.scan(domain=args.domain, top=args.top, translate=not args.no_translate)
    if args.json:
        print(json.dumps([item.as_dict() for item in items], ensure_ascii=False, indent=2))
    else:
        print(format_trending(items, args.lang))
    _checkpoint(pipeline)
    return 0 if items else 1


def cmd_daemon(args: argparse.Namespace) -> int:
    from .scheduler import run_daemon

    pipeline = _pipeline(args)
    runs = run_daemon(pipeline, pipeline.config, once=args.once, max_runs=args.max_runs, dry_run=args.dry_run)
    _checkpoint(pipeline)
    print(f"Выполнено запусков: {runs}")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    for item in pipeline.sources.status():
        state = "OPEN" if item["open"] else "ok"
        print(f"{item['name']}: {state}, ошибок {item['failures']}, tier {item['tier']}, last_ok={item['last_ok']}")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    from .metrics import MetricsCollector, format_metrics_summary

    pipeline = _pipeline(args)
    if args.collect:
        collector = MetricsCollector(pipeline.config, pipeline.storage)
        result = collector.collect(limit=args.limit, platforms=args.platform or None)
        _checkpoint(pipeline)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        print(
            f"Целей: {result['targets']} · сохранено: {result['stored']} · "
            f"пропущено: {result['skipped']} · ошибок: {result['errors']}"
        )
        for item in result["samples"]:
            detail = item["error"] or f"👁 {item['views']} ❤ {item['likes']} 💬 {item['replies']}"
            print(f"  {item['platform']}: {item['status']} {detail}")
        print()
        print(format_metrics_summary(pipeline.storage.metrics_summary()))
        return 0

    summary = pipeline.storage.metrics_summary()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_metrics_summary(summary))
    return 0


def cmd_invariants(args: argparse.Namespace) -> int:
    from .invariants import InvariantChecker

    pipeline = _pipeline(args)
    report = InvariantChecker(pipeline.storage).check()
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    elif report.ok:
        print(f"Инварианты: OK ({report.checked} проверок)")
    else:
        print(f"Инварианты: НАРУШЕНО {len(report.violations)}", file=sys.stderr)
        for item in report.violations:
            print(f"  {item.code}: {item.message} {item.detail}", file=sys.stderr)
    return 0 if report.ok else 1


def cmd_recard(args: argparse.Namespace) -> int:
    """Перерисовать карточки опубликованных постов и заменить их в канале.

    Полезно после обновления движка карточек: уже вышедшие посты получают
    новый визуал без смены message_id (подпись сохраняется).

    С ``--dry-run`` карточки только рендерятся в ``data/cards/`` и не
    отправляются в Telegram — поэтому токены в этом режиме не нужны
    (используется, например, в CI, чтобы у сайта были картинки).
    """
    import io

    import requests

    from .cards import render_card
    from .publishers.base import build_caption

    pipeline = _pipeline(args)
    storage, config = pipeline.storage, pipeline.config
    if not args.dry_run and not (config.telegram_token and config.telegram_channel):
        print("Нет TG_BOT_TOKEN/TG_CHANNEL_ID — обновление карточек невозможно", file=sys.stderr)
        return 1

    # Перерисовываем карточки ВСЕХ опубликованных постов (независимо от площадки);
    # если у поста есть telegram-сообщение — обновляем и его.
    targets: List[Dict[str, Any]] = []
    for published in storage.list_posts(status="published", limit=args.limit):
        external_id = ""
        for row in storage.publications_for(published.id):
            if row.get("platform") == "telegram" and row.get("external_id"):
                external_id = str(row["external_id"])
                break
        targets.append({"post_id": published.id, "external_id": external_id, "platform": "telegram"})
    if args.post_id:
        wanted = set(args.post_id)
        targets = [item for item in targets if item["post_id"] in wanted]
    if not targets:
        print("Опубликованных постов не найдено")
        return 1

    api = f"https://api.telegram.org/bot{config.telegram_token}"
    changed = failed = 0
    for item in targets:
        post = storage.get_post(item["post_id"])
        if post is None:
            continue
        out_path = Path(config.cards_dir) / f"{post.id}.png"
        card = render_card(post, out_path=out_path, engine=args.engine)
        if args.dry_run:
            print(f"[dry-run] {post.id} -> {card.path}")
            continue
        caption = build_caption(post, limit=1020, html=True, site_url=config.site_base_url)
        media = {"type": "photo", "media": "attach://photo", "caption": caption, "parse_mode": "HTML"}
        try:
            response = requests.post(
                f"{api}/editMessageMedia",
                data={
                    "chat_id": config.telegram_channel,
                    "message_id": item["external_id"],
                    "media": json.dumps(media, ensure_ascii=False),
                },
                files={"photo": ("card.png", io.BytesIO(card.data), "image/png")},
                timeout=25,
            )
            payload = response.json()
        except Exception as exc:
            print(f"  {item['external_id']}: ошибка {exc}", file=sys.stderr)
            failed += 1
            continue
        if not payload.get("ok"):
            print(f"  {item['external_id']}: {payload.get('description')}", file=sys.stderr)
            failed += 1
            continue
        photos = ((payload.get("result") or {}).get("photo") or [])
        file_id = photos[-1].get("file_id") if photos else ""
        storage.update_post_fields(post.id, {"card_path": str(card.path)})
        if file_id:
            storage.set_card_file_id(post.id, file_id)
        changed += 1
        print(f"  {item['external_id']}: обновлено ✓")
    _checkpoint(pipeline)
    print(f"Обновлено карточек: {changed} · ошибок: {failed}")
    return 0 if failed == 0 else 1


def cmd_drop(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    ids = args.id or []
    if not ids and args.english:
        from .text import _looks_russian

        ids = [
            post.id
            for post in pipeline.storage.list_posts(status=args.status, limit=args.limit)
            if not _looks_russian(post.title)
        ]
    if not ids:
        print("Нечего удалять.")
        return 0
    if not args.yes:
        print("Удалю посты: " + ", ".join(ids) + "\nДобавьте --yes для подтверждения.")
        return 0
    removed = sum(1 for post_id in ids if pipeline.storage.delete_post(post_id))
    _checkpoint(pipeline)
    print(f"Удалено: {removed} из {len(ids)}")
    return 0


def cmd_retranslate(args: argparse.Namespace) -> int:
    from .text import _looks_russian, formula_to_unicode, translate_preserving_latex

    pipeline = _pipeline(args)
    status = args.status or "ready"
    posts = pipeline.storage.list_posts(status=status, limit=args.limit)
    changed = 0
    untouched = 0
    for post in posts:
        updates: Dict[str, str] = {}
        for field in ("title", "hook", "body"):
            value = getattr(post, field) or ""
            if value and not _looks_russian(value):
                translated = translate_preserving_latex(value)
                if translated and translated != value:
                    updates[field] = translated
        if args.clean_latex and "body" in updates:
            updates["body"] = formula_to_unicode(updates["body"], 2000)
        if updates:
            if not args.dry_run:
                pipeline.storage.update_post_fields(post.id, updates)
            changed += 1
            print(f"  {post.id}: {', '.join(updates)}")
        else:
            untouched += 1
    _checkpoint(pipeline)
    mode = " (dry-run)" if args.dry_run else ""
    print(f"Переведено: {changed}, без изменений: {untouched} (статус {status}){mode}")
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    from .state_export import StateSync

    pipeline = _pipeline(args)
    sync = StateSync(pipeline.config, pipeline.storage)

    if args.sync:
        result = sync.sync(batch_size=args.batch_size)
        _checkpoint(pipeline)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result.get("ok"):
            print(
                f"Синхронизировано: pull {result['pull'].get('merged')}, "
                f"push {result['push'].get('rows')} строк ({result['push'].get('batches')} пачек)"
            )
        else:
            print(
                f"Sync неполный: pull={result['pull'].get('ok')} push={result['push'].get('ok')}",
                file=sys.stderr,
            )
        return 0 if result.get("ok") else 1

    if args.pull:
        result = sync.pull()
        _checkpoint(pipeline)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result.get("ok"):
            print(f"Слияние из D1 (CRDT): {result.get('merged')}")
        else:
            print(f"Pull не удался: {result.get('error')}", file=sys.stderr)
        return 0 if result.get("ok") else 1

    if args.push:
        result = sync.push(batch_size=args.batch_size)
        _checkpoint(pipeline)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result.get("ok"):
            print(
                f"Состояние отправлено в D1: {result['rows']} строк "
                f"({result['batches']} пачек) → {result.get('endpoint', '')}"
            )
        else:
            print(f"Не отправлено: {result.get('error') or result.get('failed')}", file=sys.stderr)
        return 0 if result.get("ok") else 1

    if args.export:
        sql = sync.export_sql()
        if args.export == "-":
            print(sql, end="")
        else:
            Path(args.export).write_text(sql, encoding="utf-8")
            print(f"Состояние выгружено: {args.export}")
        return 0

    counts = sync.counts()
    if args.json:
        print(json.dumps(counts, ensure_ascii=False, indent=2))
    else:
        print("Снимок состояния: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


def cmd_theme(args: argparse.Namespace) -> int:
    """Дизайн выпуска: A/B-рейтинг и переключение стиля (academic/3b1b/…)."""
    from .themes import format_design_table, set_theme

    pipeline = _pipeline(args)
    if getattr(args, "name", None):
        ok, message = set_theme(pipeline.storage, args.name)
        if not ok:
            print(message, file=sys.stderr)
            return 1
        print(message)
    print(format_design_table(pipeline.storage, pipeline.config, html=False))
    _checkpoint(pipeline)
    return 0


def cmd_film(args: argparse.Namespace) -> int:
    """Видео поста: 5-актовый Moku3D или книжный book-фильм."""
    style = str(getattr(args, "style", "moku3d") or "moku3d").lower()
    if style == "book":
        from .book_film import book_film_available, book_film_for_post

        available, build = book_film_available, book_film_for_post
        label = "book-фильм"
    elif style == "explainer":
        from .explainer_film import explainer_film_available, explainer_film_for_post

        available, build = explainer_film_available, explainer_film_for_post
        label = "Explainer"
    else:
        from .moku_film import film_available, film_for_post

        available, build = film_available, film_for_post
        label = "Moku3D"

    pipeline = _pipeline(args)
    if not available():
        print(f"{label} недоступен: не найден ffmpeg.", file=sys.stderr)
        return 1
    post = pipeline.storage.get_post(args.post_id) if getattr(args, "post_id", None) else None
    if post is None:
        post = pipeline.choose_next(getattr(args, "domain", None))
    if post is None:
        print("Нет поста для экранизации.", file=sys.stderr)
        return 1
    aspect = getattr(args, "aspect", None)
    path = build(post, pipeline.config, aspect=aspect)
    if not path:
        print(f"Не удалось собрать {label}.", file=sys.stderr)
        return 1
    print(f"Фильм: {path} ({path.stat().st_size // 1024} КБ)")
    from .video_registry import register_video

    register_video(pipeline.config, post, style, str(aspect or "auto"), path, engine=style)
    if getattr(args, "send", False):
        from .admin import TelegramAdmin

        admin = TelegramAdmin(pipeline.config, pipeline)
        if admin.send_video(path, f"{label} · {post.title}"):
            print("Отправлено в админ-чат.")
        else:
            print("Не удалось отправить в админ-чат.", file=sys.stderr)
            return 1
    _checkpoint(pipeline)
    return 0


def cmd_videos(args: argparse.Namespace) -> int:
    """Реестр сгенерированных видео."""
    from .video_registry import format_registry, list_videos

    pipeline = _pipeline(args)
    if getattr(args, "json", False):
        print(json.dumps(list_videos(pipeline.config), ensure_ascii=False, indent=2))
    else:
        print(format_registry(pipeline.config))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Мониторинг changelog'ов площадок: что изменилось и что обновить."""
    from .platform_watch import format_watch_report, watch_platforms

    pipeline = _pipeline(args)
    report = watch_platforms(pipeline.config, force=getattr(args, "force", False))
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_watch_report(report, html=False))
    if getattr(args, "send", False):
        from .admin import TelegramAdmin

        admin = TelegramAdmin(pipeline.config, pipeline)
        if not admin.available():
            print("Не могу отправить: нужны TG_BOT_TOKEN и TG_ADMIN_CHAT_ID", file=sys.stderr)
            return 1
        admin.send(format_watch_report(report, html=True))
        print("Отчёт отправлен в админ-чат.")
    _checkpoint(pipeline)
    return 0 if not report.get("errors") else 1


def cmd_next(args: argparse.Namespace) -> int:
    """Что осталось до релиза: Threads, Cloudflare, режим картинки."""
    from .release_check import format_release, release_status

    pipeline = _pipeline(args)
    report = release_status(pipeline.config)
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_release(report))
    _checkpoint(pipeline)
    ready = (
        (report.get("threads") or {}).get("state") == "ready"
        and (report.get("cloudflare") or {}).get("state") == "ready"
    )
    return 0 if ready else 1


def cmd_auth_check(args: argparse.Namespace) -> int:
    """Живой тестер ключей: безопасный read-only пинг всех площадок."""
    from .authcheck import check_all, format_auth_table

    pipeline = _pipeline(args)
    rows = check_all(pipeline.config)
    if getattr(args, "json", False):
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(format_auth_table(rows, html=False))
    _checkpoint(pipeline)
    return 0


def cmd_sync_platform(args: argparse.Namespace) -> int:
    """Догоняющая синхронизация: довыгрузить начало летописи на площадку."""
    from .sync import format_sync_report, sync_platform

    pipeline = _pipeline(args)
    result = sync_platform(
        pipeline, args.platform, limit=args.limit, dry_run=getattr(args, "dry_run", False)
    )
    print(format_sync_report(result, html=False))
    _checkpoint(pipeline)
    return 0 if result.get("ok") else 1


def cmd_sensors(args: argparse.Namespace) -> int:
    """Живые датчики Планеты и Космоса (4 бесключевых научных API)."""
    from .live_sensors import all_sensors, enable

    pipeline = _pipeline(args)
    enable(True)
    data = all_sensors()
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print("Живые датчики (без ключей)")
        for name, item in data.items():
            state = "живой" if item.get("live") else "офлайн-фоллбэк"
            print(f"  {name}: {state} · {item.get('source')}")
            for key in ("magnitude", "depth_km", "kp", "level", "name", "mass_1", "mass_2",
                        "altitude_km", "velocity_km_s", "gravity", "energy_j"):
                if key in item:
                    print(f"      {key} = {item[key]}")
    _checkpoint(pipeline)
    return 0


def cmd_rituals(args: argparse.Namespace) -> int:
    """4-уровневый календарь: что должно сработать сейчас (слоты, Пт/Сб/Вс, 1-е число)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from .rituals import daily_domain, due_rituals, news_threshold, run_rituals

    pipeline = _pipeline(args)
    now = datetime.now(ZoneInfo(pipeline.config.timezone))
    slot = daily_domain(now, pipeline.config)
    due = due_rituals(pipeline.storage, pipeline.config, now)
    print(f"Слот суток: {slot} · дисциплина: {'physics (лаборатория)' if slot == 'satellite_lab' else slot}")
    print(f"Порог «Молнии науки»: {news_threshold(pipeline.config)} лайков")
    print(f"Должно сработать: {', '.join(due) if due else 'ничего'}")
    if not args.dry_run:
        report = run_rituals(pipeline, now=now)
        for name, result in report["results"].items():
            print(f"  {name}: {result}")
    else:
        report = run_rituals(pipeline, now=now, dry_run=True)
        for name, result in report["results"].items():
            print(f"  {name} (проверка): {result}")
    _checkpoint(pipeline)
    return 0


def cmd_formal(args: argparse.Namespace) -> int:
    from .formal import check_lean

    pipeline = _pipeline(args)
    result = check_lean(pipeline.config.root)
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0 if result.ok else 1
    if not result.available:
        print("Lean не установлен: формальная проверка пропущена (см. docs/FORMAL.md)", file=sys.stderr)
        return 0
    if result.ok:
        print(f"Формальные инварианты доказаны (Lean): {result.file}")
        return 0
    print(f"Проверка Lean не прошла: {result.file}", file=sys.stderr)
    if result.error:
        print(f"  {result.error}", file=sys.stderr)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return 1


def cmd_edge(args: argparse.Namespace) -> int:
    from .edge import EdgeSync

    pipeline = _pipeline(args)
    sync = EdgeSync(pipeline.config, pipeline.storage)
    if not sync.available():
        print("Edge недоступен: задайте CF_WORKER_URL и INGEST_SECRET", file=sys.stderr)
        return 1
    result = sync.sync(limit=args.limit)
    _checkpoint(pipeline)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Edge: отправлено {result['pushed']}, ошибок {result['failed']} → {result.get('endpoint', '')}")
        for item in result["results"]:
            state = "ok" if item.get("ok") else f"error {item.get('error') or item.get('status')}"
            print(f"  {item['id']}: {state}")
    return 0 if result.get("ok") else 1


def cmd_add(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    post, errors = pipeline.add_manual_post(
        domain=args.domain,
        title=args.title,
        body=args.body,
        formula=args.formula or "",
        code=args.code or "",
    )
    if errors:
        print("Не добавлено: " + "; ".join(errors), file=sys.stderr)
        return 1
    _checkpoint(pipeline)
    print(f"Добавлено: {post.id} — {post.title}")
    return 0


def cmd_standards(args: argparse.Namespace) -> int:
    """Показать/настроить пороги качества и проверить очередь."""
    from .publishers.base import build_caption
    from .standards import Standards, StandardsChecker

    pipeline = _pipeline(args)
    checker = StandardsChecker.load(pipeline.storage, pipeline.config)
    if args.set:
        key, value = args.set
        if key not in Standards.DEFAULTS:
            print(f"Неизвестный порог: {key}. Доступно: {', '.join(Standards.DEFAULTS)}", file=sys.stderr)
            return 2
        setattr(checker.standards, key, Standards.parse_value(key, value))
        checker.save(pipeline.storage)
        print(f"{key} = {getattr(checker.standards, key)}")
        return 0
    if args.json:
        print(json.dumps(checker.standards.as_dict(), ensure_ascii=False, indent=2))
        return 0
    posts = pipeline.storage.list_posts(status=args.status, limit=args.limit)
    bad = 0
    for post in posts:
        caption = build_caption(post, 1020, True, pipeline.config.site_base_url)
        report = checker.check(post, caption)
        state = "ok" if report.ok else "нарушения: " + "; ".join(item.code for item in report.violations)
        print(f"  {post.id}: {state}")
        bad += 0 if report.ok else 1
    print(f"Проверено {len(posts)}, с нарушениями {bad}")
    return 0


def cmd_quarantine(args: argparse.Namespace) -> int:
    """Список постов в карантине (status='rejected') с причинами."""
    from .standards import StandardsChecker

    pipeline = _pipeline(args)
    posts = StandardsChecker.list_quarantine(pipeline.storage, limit=args.limit)
    if args.json:
        print(json.dumps([{"id": p.id, "title": p.title, "reason": p.meta.get("rejected_reason", "")}
                          for p in posts], ensure_ascii=False, indent=2))
        return 0
    if not posts:
        print("Карантин пуст.")
        return 0
    for post in posts:
        print(f"  {post.id}: {post.title}\n      причина: {post.meta.get('rejected_reason', '—')}")
    print(f"Всего в карантине: {len(posts)}")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    """Отправить посты в карантин вручную."""
    if not args.yes:
        print("Отказ: добавьте --yes для отправки в карантин", file=sys.stderr)
        return 2
    pipeline = _pipeline(args)
    done = 0
    for post_id in args.id or []:
        if pipeline.storage.update_post_fields(post_id, {"status": "rejected"}):
            pipeline.storage.set_post_meta(post_id, "rejected_reason", args.reason or "вручную оператором")
            done += 1
    _checkpoint(pipeline)
    print(f"В карантин отправлено: {done}")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    """Предполётная проверка следующего поста (без публикации)."""
    from .preflight import format_preflight, preflight

    pipeline = _pipeline(args)
    report = preflight(pipeline, domain=args.domain, with_media=not args.no_media)
    if args.json:
        print(json.dumps({k: v for k, v in report.items() if k != "post"}, ensure_ascii=False, indent=2))
    else:
        print(format_preflight(report))
    return 0 if report.get("ok") else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Единая верификация: инварианты, Lean, фаззинг, медиа."""
    from .verify import format_verify, run_verify

    pipeline = _pipeline(args)
    report = run_verify(pipeline, include_media=not args.no_media, include_lean=not args.no_lean)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_verify(report))
    return 0 if report.get("ok") else 1


def cmd_reorder(args: argparse.Namespace) -> int:
    """Пересортировка очереди: фундамент по ступеням, затем от простого к сложному."""
    from .curriculum import complexity_tier, format_curriculum, is_foundation

    pipeline = _pipeline(args)
    posts = pipeline.storage.list_posts(status=args.status, limit=args.limit, order="created_at ASC")
    for post in posts:
        tier = complexity_tier(post)
        try:
            pipeline.storage.set_post_meta(post.id, "complexity_tier", tier)
        except Exception:
            pass
    rows = format_curriculum(posts, limit=args.limit)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    print(f"Порядок выхода ({args.status}), фундамент первым:")
    for row in rows:
        mark = "🏛" if row["foundation"] else "  "
        step = f"ступень {row['step']}" if row["step"] else f"tier {row['tier']}"
        print(f"{row['position']:3d}. {mark} [{row['domain']:7s}] {step:12s} {row['title'][:60]}")
    foundation_count = sum(1 for post in posts if is_foundation(post))
    print(f"Всего: {len(posts)} · узлов фундамента: {foundation_count}")
    _checkpoint(pipeline)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Экскурсия по системе: отправить тур в админ-чат."""
    from .admin import TelegramAdmin
    from .demo import run_demo

    pipeline = _pipeline(args)
    admin = TelegramAdmin(pipeline.config, pipeline, chat_id=args.chat or None)
    if not admin.available():
        print("Нужен TG_BOT_TOKEN и админ-чат (--chat или TG_ADMIN_CHAT_ID)", file=sys.stderr)
        return 1
    result = run_demo(pipeline, admin, limit_posts=args.posts, with_media=not args.no_media)
    print(f"Отправлено сообщений: {result['sent']} · постов: {result['posts']}")
    return 0


def cmd_limits(args: argparse.Namespace) -> int:
    """Правила площадок: показать, изменить или сбросить."""
    from .platforms_info import PlatformRules, format_limits

    pipeline = _pipeline(args)
    rules = PlatformRules.load(pipeline.storage, pipeline.config)
    if getattr(args, "reset", False):
        rules.reset()
        rules.save(pipeline.storage)
        print("Правила площадок сброшены к значениям по умолчанию.")
        return 0
    if getattr(args, "set", None):
        platform, param, value = args.set
        try:
            parsed = rules.set(platform, param, value)
        except (KeyError, ValueError) as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 2
        rules.save(pipeline.storage)
        print(f"{platform}.{param} = {parsed}")
        return 0
    if args.json:
        print(json.dumps(rules.as_dict(), ensure_ascii=False, indent=2))
        return 0
    availability = {item["name"]: bool(item.get("available")) for item in pipeline.status().get("platforms", [])}
    print(format_limits(rules, availability or None))
    return 0


def cmd_foundation(args: argparse.Namespace) -> int:
    """Статус фундамента: с каких постов начинаем публикацию (по ступеням)."""
    from .evolve import EvolutionEngine

    pipeline = _pipeline(args)
    rows = EvolutionEngine(pipeline).foundation_status(limit=args.limit)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    current_step = None
    for row in rows:
        if row["step"] != current_step:
            current_step = row["step"]
            print(f"\nСтупень {row['step']} — {row['step_title']}:")
        print(f"  [{row['domain']:7s}] {row['title']} — {row['status']}")
    return 0


def cmd_book(args: argparse.Namespace) -> int:
    """Собрать PDF-книгу проекта из опубликованных постов (Typst)."""
    from .book import BookBuilder

    pipeline = _pipeline(args)
    builder = BookBuilder(pipeline.config, pipeline.storage)
    try:
        path = builder.build(out_pdf=args.out, limit=args.limit)
    except Exception as exc:
        print(f"Книга не собралась: {exc}", file=sys.stderr)
        return 1
    size_kb = path.stat().st_size // 1024
    print(f"Книга: {path} ({size_kb} КБ)")
    return 0


def cmd_voice(args: argparse.Namespace) -> int:
    """Озвучить пост (или очередь) и показать результат."""
    from .voice import format_voice_engines, speech_text, voice_available, voice_for_post, voice_settings

    pipeline = _pipeline(args)
    config = pipeline.config
    settings = voice_settings(config)
    if getattr(args, "engines", False):
        print(format_voice_engines(config))
        return 0
    if not voice_available(config):
        print("Нет доступного TTS: edge-tts / piper / google / espeak-ng", file=sys.stderr)
        return 1

    if args.post_id:
        posts = [pipeline.storage.get_post(pid) for pid in args.post_id]
        posts = [post for post in posts if post]
    else:
        posts = pipeline.storage.list_posts(status=args.status, limit=args.limit, order="created_at ASC")
    if not posts:
        print("Нет постов для озвучки", file=sys.stderr)
        return 1

    done = 0
    for post in posts:
        if args.text_only:
            print(f"[{post.id}] {speech_text(post, settings['max_chars'])}")
            continue
        artifact = voice_for_post(post, config)
        if artifact is None:
            print(f"  {post.id}: озвучка не удалась", file=sys.stderr)
            continue
        done += 1
        print(f"  {post.id}: {artifact.duration_s:.1f} с · {artifact.voice} · {artifact.mp3_path}")
    print(f"Озвучено постов: {done}/{len(posts)}")
    return 0 if done or args.text_only else 1


def cmd_checkpoint(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    pipeline.storage.checkpoint()
    print("WAL checkpoint выполнен.")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    if not args.yes:
        print("Отказ: для очистки базы добавьте --yes", file=sys.stderr)
        return 2
    pipeline = _pipeline(args)
    pipeline.storage.reset()
    _checkpoint(pipeline)
    print("База очищена.")
    return 0


def cmd_clean_start(args: argparse.Namespace) -> int:
    """Чистый старт: сброс состояния, обслуживание БД и пересборка сайта.

    Опасно: удаляет посты, публикации, метрики, источники и историю дублей.
    Требует явного ``--yes``.
    """
    if not args.yes:
        print("Отказ: для чистого старта добавьте --yes", file=sys.stderr)
        return 2
    pipeline = _pipeline(args)
    pipeline.storage.reset()
    try:
        pipeline.storage.checkpoint()
        pipeline.storage.vacuum()
    except Exception as exc:
        LOGGER.warning("Обслуживание БД не удалось: %s", exc)
    path = pipeline.build_site()
    print("Чистый старт выполнен: состояние сброшено, сайт пересобран.")
    print(f"Сайт: {path}")
    return 0


def cmd_staged(args: argparse.Namespace) -> int:
    """Показывает подготовленный N+1 пост (warm staging приёмочной комиссии)."""
    pipeline = _pipeline(args)
    storage, config = pipeline.storage, pipeline.config
    post_id = storage.kv_get("staged_next_post_id", "")
    post = storage.get_post(post_id) if post_id else None
    if post is None or args.next:
        from .canon_gate import CanonGate

        report = CanonGate(storage, config).stage_next(pipeline)
        if report.get("error"):
            print(f"Стейджинг не удался: {report['error']}", file=sys.stderr)
            return 1
        post = storage.get_post(str(report.get("post_id") or ""))
    if post is None:
        print("Нет подготовленного поста", file=sys.stderr)
        return 1
    meta = post.meta or {}
    print(f"§ {meta.get('section_num', '')} · {post.title} [{post.domain}] · {post.status}")
    print(f"Карточка: {post.card_path or meta.get('card_path') or '—'}")
    reasons = meta.get("reject_reasons") or []
    if reasons:
        print("Причины отказа: " + "; ".join(str(reason) for reason in reasons))
    _checkpoint(pipeline)
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """Отправляет снимок базы ``science.db`` документом в админ-чат Telegram."""
    import requests

    pipeline = _pipeline(args)
    config = pipeline.config
    path = Path(config.db_path)
    if not path.is_file():
        print("База не найдена", file=sys.stderr)
        return 1
    if not (config.telegram_token and config.telegram_admin_chat):
        print("Нет TG_BOT_TOKEN/TG_ADMIN_CHAT_ID", file=sys.stderr)
        return 1
    pipeline.storage.checkpoint()
    with path.open("rb") as handle:
        response = requests.post(
            f"https://api.telegram.org/bot{config.telegram_token}/sendDocument",
            data={
                "chat_id": config.telegram_admin_chat,
                "caption": f"🗄 Бэкап science.db · {path.stat().st_size} байт",
            },
            files={"document": (path.name, handle, "application/octet-stream")},
            timeout=60,
        )
    payload = response.json()
    if not payload.get("ok"):
        print(f"Telegram: {payload.get('description')}", file=sys.stderr)
        return 1
    print(f"Бэкап отправлен: message_id {payload['result']['message_id']}")
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    """Восстанавливает состояние из публичной ленты канала (`t.me/s/<канал>`)."""
    from .recovery import recover_from_public_channel

    pipeline = _pipeline(args)
    report = recover_from_public_channel(pipeline.storage, pipeline.config, limit=args.limit)
    if not report.get("ok"):
        print(f"Восстановление не удалось: {report.get('error')}", file=sys.stderr)
        return 1
    print(f"Восстановлено узлов: {report['recovered']} из ленты @{report['channel']}")
    for item in report.get("items", [])[:10]:
        print(f"  § {item['section']} → message_id {item['message_id']}")
    _checkpoint(pipeline)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="science_pulse",
        description="Science Pulse: детерминированная научная лента для Telegram/Threads/сайта.",
    )
    parser.add_argument("--config", help="путь к config.yaml", default=None)
    parser.add_argument("--root", help="корень проекта", default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="создать каталоги и базу")
    init.set_defaults(func=cmd_init)

    status = subparsers.add_parser("status", help="показать состояние")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    knowledge = subparsers.add_parser("knowledge", help="SCM Knowledge Base: документы, поиск, утверждения")
    knowledge.add_argument("action", nargs="?", default="stats",
                           choices=["index", "search", "stats", "claim", "note", "decisions", "integrity", "export"])
    knowledge.add_argument("value", nargs="?", default=None, help="запрос или текст утверждения/заметки")
    knowledge.add_argument("--source", default="")
    knowledge.add_argument("--status", default="UNPROVEN", choices=["PROVEN", "EMPIRIC", "HYPOTHESIS", "REFUTED", "UNPROVEN"])
    knowledge.add_argument("--limit", type=int, default=10)
    knowledge.add_argument("--json", action="store_true")
    knowledge.set_defaults(func=cmd_knowledge)

    harvest = subparsers.add_parser("harvest", help="добрать материалы")
    harvest.add_argument("--limit", type=int, default=2)
    harvest.add_argument("--domain", choices=["math", "physics", "cs"])
    harvest.add_argument("--offline", action="store_true", help="включить офлайн-бункер")
    harvest.set_defaults(func=cmd_harvest)

    publish = subparsers.add_parser("publish", help="опубликовать следующий пост")
    publish.add_argument("--dry-run", action="store_true")
    publish.add_argument("--domain", choices=["math", "physics", "cs"])
    publish.add_argument("--post-id", default=None, help="опубликовать конкретный пост")
    publish.add_argument("--target", action="append", help="площадка (можно несколько)")
    publish.add_argument("--force", action="store_true")
    publish.add_argument("--video", action="store_true", help="принудительно озвученное микро-видео")
    publish.add_argument("--no-video", action="store_true", help="только статичная карточка")
    publish.add_argument("--no-site", action="store_true")
    publish.set_defaults(func=cmd_publish)

    post = subparsers.add_parser("post", help="предпросмотр поста: карточка + подпись + описание")
    post.add_argument("--id", default=None, help="id конкретного поста")
    post.add_argument("--domain", choices=["math", "physics", "cs"])
    post.add_argument("--engine", choices=["auto", "typst", "academic", "pillow"], default="auto")
    post.add_argument("--preview", action="store_true", help="предпросмотр (режим по умолчанию)")
    post.add_argument("--send", action="store_true", help="отправить карточку с подписью в админ-чат")
    post.set_defaults(func=cmd_post)

    run = subparsers.add_parser("run", help="добыча + публикация + сайт")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--no-harvest", action="store_true")
    run.add_argument("--no-site", action="store_true")
    run.set_defaults(func=cmd_run)

    site = subparsers.add_parser("site", help="пересобрать сайт")
    site.set_defaults(func=cmd_site)

    book = subparsers.add_parser("book", help="собрать PDF-книгу проекта (Typst)")
    book.add_argument("--out", default=None, help="путь к PDF (по умолчанию dist/science_pulse_book.pdf)")
    book.add_argument("--limit", type=int, default=None, help="максимум постов в книге")
    book.set_defaults(func=cmd_book)

    voice = subparsers.add_parser("voice", help="озвучить посты (edge-tts / piper)")
    voice.add_argument("--post-id", action="append", help="id поста (можно несколько)")
    voice.add_argument("--status", default="ready", help="статус постов (по умолчанию ready)")
    voice.add_argument("--limit", type=int, default=1, help="сколько постов озвучить")
    voice.add_argument("--text-only", action="store_true", help="только показать текст для диктора")
    voice.add_argument("--engines", action="store_true", help="показать состояние TTS-движков и лимитов")
    voice.set_defaults(func=cmd_voice)

    standards = subparsers.add_parser("standards", help="пороги качества: показать/настроить/проверить")
    standards.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="изменить порог")
    standards.add_argument("--status", default="ready", help="какие посты проверять")
    standards.add_argument("--limit", type=int, default=20)
    standards.add_argument("--json", action="store_true")
    standards.set_defaults(func=cmd_standards)

    quarantine = subparsers.add_parser("quarantine", help="посты в карантине (rejected)")
    quarantine.add_argument("--limit", type=int, default=50)
    quarantine.add_argument("--json", action="store_true")
    quarantine.set_defaults(func=cmd_quarantine)

    reject = subparsers.add_parser("reject", help="отправить посты в карантин вручную")
    reject.add_argument("--id", action="append", help="id поста (можно несколько)")
    reject.add_argument("--reason", default="", help="причина")
    reject.add_argument("--yes", action="store_true")
    reject.set_defaults(func=cmd_reject)

    preflight = subparsers.add_parser("preflight", help="предполётная проверка следующего поста")
    preflight.add_argument("--domain", choices=["math", "physics", "cs"])
    preflight.add_argument("--no-media", action="store_true", help="без проверки звука и видео")
    preflight.add_argument("--json", action="store_true")
    preflight.set_defaults(func=cmd_preflight)

    verify = subparsers.add_parser("verify", help="единая верификация: инварианты, Lean, фаззинг, медиа")
    verify.add_argument("--no-media", action="store_true")
    verify.add_argument("--no-lean", action="store_true")
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(func=cmd_verify)

    foundation = subparsers.add_parser("foundation", help="статус фундамента: с каких постов начинаем")
    foundation.add_argument("--limit", type=int, default=9)
    foundation.add_argument("--json", action="store_true")
    foundation.set_defaults(func=cmd_foundation)

    limits = subparsers.add_parser("limits", help="правила площадок: лимиты и режим звука")
    limits.add_argument("--set", nargs=3, metavar=("PLATFORM", "PARAM", "VALUE"), help="изменить правило")
    limits.add_argument("--reset", action="store_true", help="сбросить к значениям по умолчанию")
    limits.add_argument("--json", action="store_true")
    limits.set_defaults(func=cmd_limits)

    demo = subparsers.add_parser("demo", help="экскурсия по системе в админ-чат")
    demo.add_argument("--chat", default=None, help="админ-чат (по умолчанию TG_ADMIN_CHAT_ID)")
    demo.add_argument("--posts", type=int, default=5, help="сколько архетипов показать")
    demo.add_argument("--no-media", action="store_true", help="без звука и видео")
    demo.set_defaults(func=cmd_demo)

    reorder = subparsers.add_parser("reorder-from-foundation",
                                    help="пересортировать очередь: фундамент → по сложности")
    reorder.add_argument("--status", default="ready", help="какой статус пересортировать")
    reorder.add_argument("--limit", type=int, default=50)
    reorder.add_argument("--json", action="store_true")
    reorder.set_defaults(func=cmd_reorder)

    admin = subparsers.add_parser("admin", help="запустить Telegram-пульт")
    admin.add_argument("--once", action="store_true", help="один проход опроса команд (для CI/cron)")
    admin.set_defaults(func=cmd_admin)

    doctor = subparsers.add_parser("doctor", help="светофор автономности (готовность к автопилоту)")
    doctor.add_argument("--send", action="store_true", help="отправить отчёт в админ-чат Telegram")
    doctor.set_defaults(func=cmd_doctor)

    growth = subparsers.add_parser("growth", help="рост аудитории: Threads-формат, UTM, реестр каналов")
    growth.add_argument("action", nargs="?", default="plan", choices=["plan", "targets", "target-add", "report", "utm", "collect", "dashboard"])
    growth.add_argument("value", nargs="?", default=None, help="URL для utm")
    growth.add_argument("--post-id", default=None)
    growth.add_argument("--platform", default=None)
    growth.add_argument("--name", default=None)
    growth.add_argument("--url", default=None)
    growth.add_argument("--topic", default="science")
    growth.add_argument("--audience", type=int, default=0)
    growth.add_argument("--notes", default="")
    growth.add_argument("--status", default=None)
    growth.add_argument("--limit", type=int, default=100)
    growth.add_argument("--json", action="store_true")
    growth.set_defaults(func=cmd_growth)

    signal = subparsers.add_parser("signal", help="математический движок сигналов (5 законов книги)")
    signal.add_argument("--json", action="store_true")
    signal.set_defaults(func=cmd_signal)

    trending = subparsers.add_parser("trending", help="радар мировых научных новостей (HN + Reddit)")
    trending.add_argument("--domain", choices=["math", "physics", "cs"], default=None)
    trending.add_argument("--top", type=int, default=5)
    trending.add_argument("--lang", choices=["ru", "en"], default="ru")
    trending.add_argument("--no-translate", action="store_true")
    trending.add_argument("--json", action="store_true")
    trending.set_defaults(func=cmd_trending)

    daemon = subparsers.add_parser("daemon", help="запустить планировщик")
    daemon.add_argument("--once", action="store_true")
    daemon.add_argument("--dry-run", action="store_true")
    daemon.add_argument("--max-runs", type=int, default=None)
    daemon.set_defaults(func=cmd_daemon)

    sources = subparsers.add_parser("sources", help="показать здоровье источников")
    sources.set_defaults(func=cmd_sources)

    add = subparsers.add_parser("add", help="добавить ручной пост в очередь")
    add.add_argument("--domain", choices=["math", "physics", "cs"], required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--body", required=True)
    add.add_argument("--formula", default="")
    add.add_argument("--code", default="")
    add.set_defaults(func=cmd_add)

    checkpoint = subparsers.add_parser("checkpoint", help="сбросить WAL в основной файл БД")
    checkpoint.set_defaults(func=cmd_checkpoint)

    metrics = subparsers.add_parser("metrics", help="собрать/показать метрики площадок")
    metrics.add_argument("--collect", action="store_true", help="опросить площадки и сохранить замеры")
    metrics.add_argument("--limit", type=int, default=50, help="сколько публикаций опросить")
    metrics.add_argument("--platform", action="append", help="площадка (можно несколько)")
    metrics.add_argument("--json", action="store_true")
    metrics.set_defaults(func=cmd_metrics)

    invariants = subparsers.add_parser("invariants", help="проверить инварианты состояния")
    invariants.add_argument("--json", action="store_true")
    invariants.set_defaults(func=cmd_invariants)

    edge = subparsers.add_parser("edge", help="синхронизировать карточки/узлы с Cloudflare R2/D1")
    edge.add_argument("--limit", type=int, default=20, help="сколько постов отправить")
    edge.add_argument("--json", action="store_true")
    edge.set_defaults(func=cmd_edge)

    formal = subparsers.add_parser("formal", help="машинно проверить Lean-доказательства инвариантов")
    formal.add_argument("--json", action="store_true")
    formal.set_defaults(func=cmd_formal)

    state = subparsers.add_parser("state", help="снимок состояния: экспорт SQL / реплика в D1")
    state.add_argument("--export", default=None, help="путь для SQL-дампа ('-' = stdout)")
    state.add_argument("--pull", action="store_true", help="забрать снимок из D1 и слить (CRDT)")
    state.add_argument("--push", action="store_true", help="отправить снимок в D1 через Worker")
    state.add_argument("--sync", action="store_true", help="pull → push")
    state.add_argument("--batch-size", type=int, default=200, help="размер пачки при отправке")
    state.add_argument("--json", action="store_true")
    state.set_defaults(func=cmd_state)

    retranslate = subparsers.add_parser("retranslate", help="перевести посты в очереди на русский (gtx)")
    retranslate.add_argument("--status", default="ready")
    retranslate.add_argument("--limit", type=int, default=500)
    retranslate.add_argument("--dry-run", action="store_true")
    retranslate.add_argument("--clean-latex", action="store_true", help="заменить LaTeX в body на Unicode")
    retranslate.set_defaults(func=cmd_retranslate)

    drop = subparsers.add_parser("drop", help="удалить посты из очереди (--id … или --english)")
    drop.add_argument("--id", action="append", help="id поста (можно несколько)")
    drop.add_argument("--english", action="store_true", help="удалить посты с англоязычным заголовком")
    drop.add_argument("--status", default="ready")
    drop.add_argument("--limit", type=int, default=500)
    drop.add_argument("--yes", action="store_true")
    drop.set_defaults(func=cmd_drop)

    recard = subparsers.add_parser("recard", help="перерисовать карточки опубликованных постов и заменить в канале")
    recard.add_argument("--post-id", action="append", help="id поста (можно несколько)")
    recard.add_argument("--limit", type=int, default=100)
    recard.add_argument("--engine", choices=["auto", "typst", "academic", "pillow"], default="auto")
    recard.add_argument("--dry-run", action="store_true")
    recard.set_defaults(func=cmd_recard)

    theme = subparsers.add_parser("theme", help="дизайн выпуска: A/B-рейтинг или переключение")
    theme.add_argument("name", nargs="?", help="auto|academic|3b1b|blueprint|moku3d|bookfilm")
    theme.set_defaults(func=cmd_theme)

    film = subparsers.add_parser("film", help="5-актовый фильм Moku3D (moku_film)")
    film.add_argument("--style", default="moku3d", choices=["moku3d", "book", "explainer"],
                      help="видео-движок: moku3d, book или explainer (инфографика)")
    film.add_argument("--post-id", default=None, help="id поста (по умолчанию — следующий)")
    film.add_argument("--domain", default=None, choices=["math", "physics", "cs"])
    film.add_argument("--aspect", default=None, choices=["1:1", "9:16"],
                      help="формат кадра: 1:1 (лента) или 9:16 (Reels/Shorts/VK Клипы)")
    film.add_argument("--send", action="store_true", help="отправить фильм в админ-чат")
    film.set_defaults(func=cmd_film)

    auth_check = subparsers.add_parser("auth-check", help="живой тестер ключей площадок (read-only)")
    auth_check.add_argument("--json", action="store_true")
    auth_check.set_defaults(func=cmd_auth_check)

    next_parser = subparsers.add_parser("next", help="что осталось до релиза: Threads + Cloudflare")
    next_parser.add_argument("--json", action="store_true")
    next_parser.set_defaults(func=cmd_next)

    videos = subparsers.add_parser("videos", help="реестр сгенерированных видео")
    videos.add_argument("--json", action="store_true")
    videos.set_defaults(func=cmd_videos)

    watch = subparsers.add_parser("watch", help="мониторинг changelog'ов Telegram/Threads/Cloudflare/GitHub")
    watch.add_argument("--json", action="store_true")
    watch.add_argument("--send", action="store_true", help="отправить отчёт в админ-чат")
    watch.add_argument("--force", action="store_true", help="считать всё изменённым")
    watch.set_defaults(func=cmd_watch)

    sync_platform_parser = subparsers.add_parser(
        "sync-platform", help="довыгрузить пропущенную летопись на новую площадку"
    )
    sync_platform_parser.add_argument("platform", help="telegram|threads|bluesky|discord|mastodon|vk")
    sync_platform_parser.add_argument("--limit", type=int, default=5)
    sync_platform_parser.add_argument("--dry-run", action="store_true")
    sync_platform_parser.set_defaults(func=cmd_sync_platform)

    sensors = subparsers.add_parser("sensors", help="живые датчики Планеты и Космоса (без ключей)")
    sensors.add_argument("--json", action="store_true")
    sensors.set_defaults(func=cmd_sensors)

    rituals = subparsers.add_parser("rituals", help="4-уровневый календарь: слоты, Пт/Сб/Вс, 1-е число")
    rituals.add_argument("--dry-run", action="store_true", help="только показать, что должно сработать")
    rituals.set_defaults(func=cmd_rituals)

    reset = subparsers.add_parser("reset", help="очистить состояние (опасно)")
    reset.add_argument("--yes", action="store_true")
    reset.set_defaults(func=cmd_reset)

    clean = subparsers.add_parser("clean-start", help="чистый старт: сброс + VACUUM + пересборка сайта")
    clean.add_argument("--yes", action="store_true")
    clean.set_defaults(func=cmd_clean_start)

    staged = subparsers.add_parser("staged", help="подготовленный N+1 пост (warm staging)")
    staged.add_argument("--next", action="store_true", help="подготовить заново")
    staged.set_defaults(func=cmd_staged)

    backup = subparsers.add_parser("backup", help="отправить снимок science.db в админ-чат Telegram")
    backup.set_defaults(func=cmd_backup)

    recover = subparsers.add_parser("recover-from-channel", help="восстановить состояние из ленты t.me/s/<канал>")
    recover.add_argument("--limit", type=int, default=100)
    recover.set_defaults(func=cmd_recover)

    radio = subparsers.add_parser("radio", help="научное радио: страница, подкаст, микс, RTMP")
    radio.add_argument("--mix", action="store_true", help="собрать сквозной радио-микс (ffmpeg)")
    radio.add_argument("--rtmp", default="", help="RTMP-URL для круглосуточного вещания")
    radio.add_argument("--run", action="store_true", help="реально запустить ffmpeg-вещание")
    radio.add_argument("--json", action="store_true", help="машиночитаемый отчёт")
    radio.set_defaults(func=cmd_radio)

    kernel = subparsers.add_parser("kernel", help="центральное ядро: паспорт состояния или 6-фазный цикл")
    kernel.add_argument("--tick", action="store_true", help="выполнить полный 6-фазный цикл")
    kernel.add_argument("--status", action="store_true", help="паспорт состояния (по умолчанию)")
    kernel.add_argument("--count", type=int, default=None, help="сколько тем курса добрать")
    kernel.add_argument("--no-expand", action="store_true", help="не добирать темы курса")
    kernel.add_argument("--no-site", action="store_true", help="не пересобирать сайт")
    kernel.add_argument("--publish", action="store_true", help="публиковать и готовить N+1")
    kernel.add_argument("--voice", action="store_true", help="озвучивать лекцию")
    kernel.add_argument("--formal", action="store_true", help="проверить Lean-доказательства")
    kernel.add_argument("--deep", action="store_true", help="рекурсивный обход категорий (нужна сеть)")
    kernel.add_argument("--depth", type=int, default=1, help="глубина обхода подкатегорий")
    kernel.add_argument("--json", action="store_true", help="машиночитаемый отчёт")
    kernel.set_defaults(func=cmd_kernel)

    expand = subparsers.add_parser("expand", help="добрать темы университетского курса в очередь")
    expand.add_argument("--count", type=int, default=6, help="сколько тем добавить")
    expand.add_argument("--deep", action="store_true", help="плюс обход мета-каталогов (нужна сеть)")
    expand.add_argument("--depth", type=int, default=1, help="глубина обхода подкатегорий")
    expand.add_argument("--json", action="store_true", help="машиночитаемый отчёт")
    expand.set_defaults(func=cmd_expand)

    quiz = subparsers.add_parser("quiz", help="нативная викторина по задаче следующего выпуска")
    quiz.add_argument("--domain", default=None, help="дисциплина (math/physics/cs)")
    quiz.add_argument("--send", action="store_true", help="отправить опрос в канал (нужен токен)")
    quiz.add_argument("--json", action="store_true", help="машиночитаемый отчёт")
    quiz.set_defaults(func=cmd_quiz)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Остановлено.", file=sys.stderr)
        return 130
    except Exception as exc:
        LOGGER.exception("Ошибка: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
