# Литература SCM

Библиография рабочей части проекта: сигналы, информация, научный текст,
публицистика, коммерция. Внутренние документы — часть проекта; внешние книги —
основание методов, а не «источник фактов» без проверки.

## 1. Сигналы и информация

| Источник | Зачем SCM |
|:--|:--|
| Зюко А. Г., Кловский Д. Д., Назаров М. В., Финк Л. М. **Теория передачи сигналов**. М.: Связь, 1980 | объём сигнала `Vc=Tc·Fc·Hc`, ёмкость канала, УОС/РОС, защитные интервалы |
| Shannon C. E. **A Mathematical Theory of Communication** // Bell System Technical Journal, 1948 | энтропия, избыточность, пропускная способность |
| Kotelnikov V. A. **On the transmission capacity of “ether” and wire in electrocommunications**, 1933 | теорема отсчётов, шаг `1/(2Fmax)` |
| Hamming R. W. **Error Detecting and Error Correcting Codes** // Bell System Technical Journal, 1950 | код (7,4), расстояние 3, исправление ошибки |

## 2. РИИ и формальная проверка

| Источник | Зачем SCM |
|:--|:--|
| Косяков А. **Мой мозг** (2001) | теория памяти/эталонов, на которую опирается РИИ |
| `RII/docs/RII_MASTER.md` | рабочий канон РИИ |
| `RII/docs/UNDERSTANDING_RII_FULL.md` | понятная карта РИИ |
| `RII/docs/RII_CANON_MASTER.md` | проверенный мастер и границы |
| `RII Lab` / `docs/BENCHMARK*.md` | CEGIS, Z3, Lean, сертификаты |
| `KERN/docs/CHARTER.md`, `CAPABILITY_MATRIX.md` | ворота верификации, `e=1` |
| Lean 4 documentation | формальные инварианты SCM |
| Z3 documentation | SMT-проверки |

## 3. Научный и публицистический текст

| Источник | Зачем SCM |
|:--|:--|
| Schimel J. **Writing Science** | структура научного рассказа: вопрос → метод → результат |
| Pinker S. **The Sense of Style** | ясность, ритм, борьба с канцеляритом |
| Williams J., Bizup J. **Style: Lessons in Clarity and Grace** | редактура предложений |
| Heath C., Heath D. **Made to Stick** | «липкость» идеи: простота, неожиданность, конкретность |
| Cialdini R. **Influence** | внимание и убедительность без манипуляции фактами |
| Kahneman D. **Thinking, Fast and Slow** | когнитивная нагрузка читателя |

## 4. Коммерческая ветка

| Источник | Зачем SCM |
|:--|:--|
| Weinberg G., Mares J. **Traction** | каналы привлечения аудитории |
| Croll A., Yoskovitz B. **Lean Analytics** | одна ключевая метрика, воронка, когорты |
| Ries E. **The Lean Startup** | гипотеза → измерение → вывод |
| Osterwalder A., Pigneur Y. **Business Model Generation** | продуктовая линейка и ценность |

## 5. Внутренние документы SCM

- `docs/SCM.md` — парадигма;
- `docs/OPERATOR.md` — вход оператора;
- `docs/ECOSYSTEM.md` — место в экосистеме;
- `docs/KNOWLEDGE_BASE.md` — база знаний;
- `docs/RUNBOOKS.md` — запуск/восстановление;
- `docs/SECURITY.md` — секреты;
- `docs/DECISIONS.md` — решения;
- `docs/GLOSSARY.md` — термины;
- `docs/PLAN.md` — план разработки;
- `docs/PROD_CHECKLIST.md` — боевой запуск.

## 6. Правило использования

Книга даёт **метод**, но не факт о мире. Факт в SCM должен иметь источник
(статья, API, документ, оракул) и статус. Ссылка на книгу без проверки —
`HYPOTHESIS`, не `PROVEN`.
