# Правила площадок: лимиты и звук (PlatformRules)

Единый реестр `DEFAULT_PLATFORM_RULES` в `science_pulse/platforms_info.py`.
Публикаторы **не хардкодят** лимиты — они читают их отсюда, поэтому смена
правил соцсети не требует правки кода.

## Матрица по умолчанию

| Площадка | Текст ≤ | Цепочка ≤ | Звук | Как доставляется |
|:--|--:|--:|:--|:--|
| `telegram` | 1024 | 2 | `auto` | `sendVoice` (.ogg) до 60 с, длинное — `sendAudio` (.mp3) |
| `threads` | 500 | 2 | `link` | ссылка «🎧 Слушать на сайте» (или `mp4` — видео-аудиограмма) |
| `bluesky` | 300 | 1 | `link` | ссылка на аудио-разбор |
| `discord` | 2000 (embed 4096) | 1 | `file` | mp3 вторым вложением в webhook |
| `mastodon` | 500 | 1 | `file` | mp3 как media (Mastodon играет нативно) |
| `vk` | 16384 | 1 | `link` | ссылка в тексте записи |

Режимы звука (`audio_mode`): `auto`, `voice`, `audio`, `mp4`, `file`, `link`, `off`.
Глобальный выключатель озвучки остаётся `voice.enabled: false` в `config.yaml`.

## Почему для Threads/Bluesky/VK — `link` или `mp4`

Эти сети **не принимают «голые» `.ogg`/`.mp3`**. Решения:

- `link` — в текст добавляется ссылка на страницу поста, где есть `<audio>`-плеер;
- `mp4` — `voice.build_audiogram_mp4` склеивает карточку 1080×1080 и голос в
  видеоролик (`ffmpeg -loop 1 -i card.png -i audio.mp3 -tune stillimage …`),
  который уходит как видео. Работает и для `sendVideo` в Telegram.

## Переопределение на лету

Приоритет: **kv** (`platform_rules_override`) → **config.yaml** (`platform_rules:`) → **дефолт**.

```bash
python -m science_pulse.cli limits                              # таблица
python -m science_pulse.cli limits --set threads max_caption_chars 600
python -m science_pulse.cli limits --set telegram audio_mode audio
python -m science_pulse.cli limits --reset
```

В пульте то же самое:

```
/limits
/limits set threads max_caption_chars 600
/limits set telegram audio_mode voice
/limits reset
```

Примеры из жизни:

- Threads поднял лимит до 800 → `/limits set threads max_caption_chars 800`;
- хотите в Telegram не голосовое, а подкаст → `/limits set telegram audio_mode audio`;
- временно выключить звук в Bluesky → `/limits set bluesky audio_mode off`;
- отправлять в Threads ролики со звуком → `/limits set threads audio_mode mp4`.

## Прямая загрузка видео и авто-адрес сайта

Bluesky и VK принимают `.mp4` **напрямую с диска**, без публичного URL:

- Bluesky: `com.atproto.repo.uploadBlob` с `Content-Type: video/mp4` →
  `app.bsky.embed.video` (режим `audio_mode: mp4`);
- VK: `video.save` → `upload_url` → загрузка файла → `video{group}_{id}` в стене.

`SP_SITE_BASE_URL` больше не обязателен для ручного ввода: если он не задан в
`config.yaml`/`.env`, адрес определяется из `git remote get-url origin`:

```
git@github.com:newmathphys/science-pulse.git  →  https://newmathphys.github.io/science-pulse
https://github.com/newmathphys/science-pulse  →  https://newmathphys.github.io/science-pulse
git@github.com:newmathphys/kern.git           →  (пусто: чужой проект игнорируется)
```

Он нужен только для Threads (`link`/`mp4` по публичному URL) и Mini App.

## Конфигурация в config.yaml

```yaml
platform_rules:
  threads:
    max_caption_chars: 600
  telegram:
    audio_mode: audio
```

## Проверка

```bash
python -m unittest tests.test_platform_rules -v
python -m science_pulse.cli limits --json
```