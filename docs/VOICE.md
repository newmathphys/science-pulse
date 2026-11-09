# Озвучка постов (звук)

Модуль `science_pulse/voice.py` превращает пост в речь и публикует её рядом с
карточкой: голосовым сообщением (OGG/OPUS) или аудио-подкастом (MP3).

**Принцип «без LLM» не нарушается:** это синтез речи, а не генерация текста.
Текст берётся ровно тот, что уже есть в посте.

## Движки

| Движок | Сеть | Что нужно | Особенности |
|:--|:--|:--|:--|
| `edge` | нужна | `pip install edge-tts` | бесплатно, без ключей, голос `ru-RU-SvetlanaNeural` |
| `piper` | не нужна | бинарь `piper` + ONNX-модель | офлайн-синтез в духе офлайн-бункера |
| `google_tts` | нужна | `ffmpeg`, без ключей | резервный Google Translate TTS, куски ≤180 символов |
| `espeak` | не нужна | `espeak-ng` | rule-based TTS без нейросети, последний голосовой рубеж |
| `sonification` | не нужна | `ffmpeg` | научный звук формулы без слов |

## Адаптивная цепочка и лимиты

Порядок по умолчанию:

```text
edge → piper → google_tts → espeak → sonification
```

Для каждого движка хранится состояние в `data/audio/voice_health.json`:
`failures`, `blocked_until`, `last_error`, `last_kind`, `last_ok`.

- успех — счётчик сбоев сбрасывается;
- HTTP 429 / лимит — движок уходит в cooldown (60 мин, затем 2 ч, 4 ч, максимум 6 ч);
- таймаут/сеть — cooldown 10–15 мин;
- пустой/битый звук — cooldown 10 мин;
- после cooldown движок снова пробуется автоматически;
- если облачный движок в лимите, работают остальные;
- если не осталось ни одного TTS — включается сонификация.

Кэш хранится **по движку** (`<id>.edge.mp3`, `<id>.piper.mp3`, …), поэтому
возврат качественного движка после лимита автоматически вытесняет fallback.
Сонификация не кэшируется.

Посмотреть состояние:

```bash
python -m science_pulse.cli voice --engines
python -m science_pulse.cli doctor
```

⚠️ Сонификация **не кэшируется**: у неё не пишется `<id>.key`. Иначе, когда TTS
пропадёт из окружения (например, после переустановки Python без `edge-tts`),
файл-заглушка «залипнет» под ключом настоящей речи и голос не вернётся даже
после восстановления движка. Диагностика и чистка:

```bash
python -m science_pulse.cli preflight        # 🟢 voice: TTS-цепочка готова
python -c "import edge_tts; print('ok')"     # есть ли движок в этом Python
ffprobe -v error -show_entries format=bit_rate -of csv=p=0 data/audio/<id>.mp3
#  48 000 / ~32 000 бит/с — речь диктора;  ~96 000 и секунды длительности — сонификация
rm -f data/audio/<id>.key                    # снять кэш и переозвучить пост
```

Офлайн-резерв без нейросети:

```bash
sudo apt-get install -y espeak-ng
```

Установка edge-tts в окружении без `pip` (проверено вживую):

```bash
uv pip install --python python3 --target "$(python3 -c 'import site; print(site.getusersitepackages())')" 'edge-tts>=7.0'
```

⚠️ Проверено на живой сети: голос `ru-RU-SvetlanaNeural` отдаёт аудио,
а `ru-RU-DmitryNeural` / `en-US-AriaNeural` в 2026 возвращают пустой поток —
модуль сам перебирает список голосов и берёт первый рабочий.

## Форматы и куда публикуется

- **`voice`** — OGG/OPUS (32 кбит/с, моно) → Telegram `sendVoice` ответом на
  карточку. Для голосового берётся текст до 60 секунд.
- **`audio`** — MP3 → Telegram `sendAudio` (аудио-подкаст с названием и
  исполнителем).
- **Сайт** — `dist/audio/<id>.mp3` + плеер «Слушать» на странице поста.
- **Пульт** — `/voice`: озвучить следующий пост и прислать в личку.

Конвертация MP3 → OGG/OPUS делается системным `ffmpeg`.

## Лекционный сценарий диктора и субтитры

`build_lecture_script(post)` собирает для диктора **чистый лекционный рассказ**:

```
Раздел Физика. 1926 год, Цюрих. Эрвин Шрёдингер.
Шрёдингер: волновое уравнение и рождение квантовой механики.
Как одна дифференциальная формула описывает атомы? …
Применение сегодня: квантовая химия, транзисторы, лазеры.
Формула: аш с чертой, производная по тэ…
```

- вырезаются URL, `#хэштеги`, `@упоминания`, эмодзи и технические пометки;
- формулы проходят через `math_to_spoken_russian` («о большое от эн логарифм эн»);
- рядом с аудио сохраняются **синхронные субтитры** `.vtt` и `.srt`
  (таймкоды `SentenceBoundary`/`WordBoundary` из edge-tts; при кэше —
  приблизительные по длине фраз);
- на сайте плеер подключает `<track kind="subtitles">`.

## Живой чертёж в видео-аудиограмме

`audiogram_for_post(..., animate=True)` собирает ролик, где вместо статичной
карточки **постепенно прорисовывается чертёж** (36 кадров, растянутых на
длительность голоса), снизу пульсирует осциллограмма `showwaves`, а звучит
лекция диктора. Отключить: `animate=False`.

## Конфигурация

```yaml
voice:
  enabled: true
  engine: "auto"                  # auto | edge | piper | google_tts | espeak
  voice: "ru-RU-SvetlanaNeural"
  rate: "+0%"
  max_chars: 750                  # ≈55 секунд речи
  publish: "voice"                # voice (OGG/OPUS) | audio (MP3-подкаст)
  piper_model: ""                 # путь к ONNX-модели для офлайн-синтеза
  priority: ["edge", "piper", "google_tts", "espeak", "sonification"]
  edge:
    failure_threshold: 2
    cooldown_minutes: 60
    max_cooldown_minutes: 360
  google:
    failure_threshold: 1
    cooldown_minutes: 120
    max_cooldown_minutes: 360
  espeak:
    enabled: true
    voice: "ru"
    speed: 150
  google_fallback: true           # резервный Google TTS после edge/piper
```

## Короткая озвучка book-фильма

`film_voice_for_post(post, config)` собирает сценарий ≤360 символов и
синтезирует отдельный файл `<id>_film.mp3`. Это даёт 25–35 секунд речи и
5 сцен по 5–7 секунд. Edge-tts режет текст на куски и делает до 5 повторов
на кусок; эталонный голос — `ru-RU-SvetlanaNeural`.

## Пост ≠ радио

`build_lecture_script(..., closing="post")` завершает пост фразой
«Разбор завершён.». Радио (`radio.py`) передаёт `closing="radio"` и получает
«Эфир продолжается.». Поэтому в постах и book-фильмах больше нет
радио-подписи.

## Что читает диктор

`build_lecture_script(post)` собирает лекционный сценарий: «Раздел <дисциплина>.
<эпоха>, <учёный>. <заголовок>. <вопрос-крючок>. <суть разбора>. Применение
сегодня: <modern_application>. Формула: <формулы словами>». URL, хэштеги,
@упоминания, эмодзи и код вырезаются; обрезка — по границе предложения.

## Кэш и детерминированность

Итоговый файл — `data/audio/<id>.mp3|.ogg` (+ `<id>.vtt`/`.srt` — субтитры).
Кэш каждого движка лежит отдельно: `<id>.edge.mp3`, `<id>.piper.mp3`,
`<id>.google_tts.mp3`, `<id>.espeak.mp3` с ключами `<id>.<engine>.key`.
Повторный запуск не переозвучивает пост, пока текст не изменился.

Ключ пишется **только для настоящего синтеза**. Фоллбэк-сонификация ключ не
пишет и снимает `<id>.key`, поэтому возвращение качественного движка
автоматически возвращает голос — без ручной чистки кэша.

## Команды

```bash
python -m science_pulse.cli voice --post-id <id>       # озвучить пост
python -m science_pulse.cli voice --engines            # состояние TTS и лимитов
python -m science_pulse.cli voice --status ready --limit 3
python -m science_pulse.cli voice --post-id <id> --text-only   # только текст
python -m science_pulse.cli doctor                     # светофор: строка «Озвучка постов»
```

## Проверка

```bash
python -m unittest tests.test_voice -v
python -m science_pulse.cli voice --post-id <id>       # живой синтез (нужна сеть)
```