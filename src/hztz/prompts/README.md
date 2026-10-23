# Система промтов `hz`

Одна модель данных, одни правила работы с неопределённостью, один контракт между стадиями. Команды описаны в [`../cli.md`](../cli.md), состояние — в [`../state.md`](../state.md). Здесь — только то, что уходит в LLM и что от неё возвращается.

---

## 1. Структура

```text
prompts/
  README.md                 этот файл: композиция, контракты, runtime context, примеры
  common/
    system.md               базовый system prompt: принцип, уровни достоверности, правила
    model.md                модель данных: сущности, enum'ы, id/keys, evidence, envelope
    schema.json             общие $defs для JSON Schema: finding, question, option, basis, blocked
  audit/
    extract.md              стадия 1: spec → R + summary
    findings.md             стадия 2: R → A
    questions.md            стадия 3: A → O
    schema/{extract,findings,questions}.json
  decompose/
    prompt.md               R + D + open → B + T (+ uncertainties)
    schema.json
  next/
    context.md              только для --prompt: T + repo → conventions, approach
    schema.json
    handoff.md              шаблон брифа исполнителю (рендерит CLI, не system prompt)
  chat/
    prompt.md               базовый чат
    schema.json
    personas/columbo.md
    personas/feynman.md
```

Отличия от предложенной в брифе структуры:

- `terminology.md` и `output.md` слиты в `model.md`. Терминология — это и есть значения enum'ов модели; отдельный файл дублировал бы их. Правила вывода (evidence, envelope, keys) тоже часть модели.
- `audit` — три файла, не один. Стадии имеют разные входы, разные схемы и валидируются отдельно; один промт «проверь всё» — то, от чего мы уходим (`../review.md` §2.1).
- У `next` два файла: `context.md` — промт LLM (маленький), `handoff.md` — шаблон того, что видит исполнитель. Это разные адресаты.
- Общие `$defs` в `common/schema.json`: `finding` и `question` используются и `audit`, и `decompose`.

Промты написаны по-английски (стабильнее для моделей), с правилом «человекочитаемый текст — на языке ТЗ». Плейсхолдеры — Jinja (`{{var}}`, `<tag>`-блоки в user message).

---

## 2. Композиция

```text
system  =  common/system.md
        +  common/model.md
        +  <stage>/…​.md
        +  chat/personas/<persona>.md        (только chat)

user    =  runtime context: тегированные блоки <spec>…</spec>, <requirements>…</requirements> …
        +  для chat: <history>, последнее сообщение пользователя

response_format = JSON Schema стадии (structured output; fallback — tool-calling для endpoint'ов без `response_format`)
```

Правила:

1. Общие правила живут **только** в `common/`. Промт стадии не повторяет их, а ссылается («см. модель данных»).
2. Промт стадии содержит: Mission, Input (какие блоки придут), Procedure, Output (имя схемы), Constraints. Role вынесена в `system.md` — одна на всех.
3. Схема передаётся API как `response_format`, не текстом в промте. В промте — только смысл полей, где он неочевиден.
4. Всё, что можно вычислить без LLM, делает Python **до** вызова (выбор задачи, граф, статусы) или **после** (id, сопоставление по ключам, проверка ссылок).

---

## 3. Кто что делает: Python vs LLM

| Python | LLM |
| --- | --- |
| Чтение файлов, нумерация строк, хеши, снимки | Сегментация ТЗ на `R` |
| Присвоение id, замена `key` → id, счётчики | Обнаружение `A`, формулирование `O` |
| Проверка: ссылки существуют, `depends_on` без циклов, у `A` есть evidence, у `O` — ≥1 `A` | Группировка `A → O`, аудитория, варианты с основанием |
| Сопоставление по точному ключу; если LLM вернула `matches` — доверять после проверки типа | Сопоставление «тот же смысл, другая формулировка» (`matches`) |
| Severity `O` = max severity её `A`; блокировка `T` по `blocked_by` | Severity и confidence `A` |
| Выбор следующей `T`, статусы, `needs_review`, `dropped`, индекс рёбер | Нарезка `B`+`T`, порядок, контракт блока, done-when |
| Кандидаты файлов по путям для `next --prompt` | Выбор образцов, конвенции, подход |
| Рендер `audit.md`, `decomposition.md`, `handoff.md` | — |
| Исполнение слэш-команд чата после подтверждения | Классификация реплики, proposals |

---

## 4. Флаги → промт

| Команда | Влияет на LLM | Только CLI (в промт не попадает) |
| --- | --- | --- |
| `audit SPEC` | `SPEC` → `<spec>`; наличие старого состояния → `<previous_requirements>`, `<existing_findings>`, `<existing_questions>`, `<decisions>`; `state.repo` → `<repo_context>` | `-o`, `--json`, `--check`, `--reset`, `-q/-v/-y` |
| `audit ID --answer/--assume/--dismiss`, `--question`, `--resolve` | **LLM не вызывается.** Ручной `--question` получает `audience: technical` по умолчанию (см. §9.3) | всё |
| `decompose` | `state` → `<summary> <requirements> <decisions> <open_items>`; `--repo` → `<repo_context>`; существующие `B`/`T` → `<existing_blocks> <existing_tasks>` | `--reset`, `-o`, `--json` |
| `next`, `--list`, `--start`, `--done` | **LLM не вызывается** | всё |
| `next [T\|B] --prompt` | выбранная `T` + её `B` → `<task> <block> <requirements> <decisions>`; файлы блока → `<task_files> <candidates>` | выбор `T`, `-q` |
| `chat` | `--persona` → какой файл персоны добавить; `ID` → `<focus>`; `--resume` → `<history>`, `<state_delta>`; `-m` → одно сообщение | сохранение сессии, исполнение `/команд`, `-y` |
| глобальные `--model` | модель — да; текст промта — нет | `--json -q -v -y` |

Принцип: флаг попадает в промт только если меняет **что** анализировать или **в каком контексте**. Флаги формата, вывода и подтверждений — не попадают никогда.

---

## 5. Контракт между стадиями

```text
audit/extract    →  R[], summary                     →  state
audit/findings   ←  R[], spec, repo?, D?, A_old?      →  A[] (key, matches)
audit/questions  ←  A_open[], O_old?, repo?, spec     →  O[] (key, matches, findings=A ids)
CLI --answer     ←  человек                           →  D
decompose        ←  summary, R_active, D_current,
                    open A/O, repo?, B_old?, T_old?   →  B[], T[], uncertainties(A+O), uncovered, skipped
next (python)    ←  T[] + рёбра B/D/A/O              →  выбранная T
next/context     ←  T, B, R, D, repo files            →  conventions, approach, uncertainties
next/handoff     ←  T, B, R, D, context, open_items   →  markdown для исполнителя
chat             ←  spec, state-projection, focus?,
                    history, persona                  →  reply, kind, references, proposals
CLI /команда     ←  proposal + подтверждение          →  тот же путь, что audit/next флаги
```

Что переходит между командами (по брифу):

| Переход | Данные | Через |
| --- | --- | --- |
| `audit → chat` | `R A O D` + summary как `<state>`; конкретный объект как `<focus>` | `state.json` |
| `audit → decompose` | `summary`, активные `R`, актуальные `D`, открытые `A/O` с severity | `state.json` |
| `chat → decompose` | ничего напрямую: чат порождает `D`/`O` только через CLI-команды, `decompose` читает их из состояния | `state.json` |
| `decompose → next` | `B[]`, `T[]` с `order`, `depends_on`, `blocked_by`, `T.block` | `state.json` |
| `decompose → audit` | новые `A/O` из `uncertainties` (`created_by: decompose`) | `state.json` |
| `next → audit` | вопрос из реализации: `hz audit --question … --for T` | CLI |

Инвариант: **ни одна стадия не читает выход другой стадии напрямую** — только через провалидированное состояние. Поэтому промты не зависят от формулировок друг друга, только от модели.

---

## 6. Runtime context

Python подставляет блоки в user message. Пустые/неприменимые блоки не подставляются вовсе (не «пустой тег»), чтобы промт не намекал на отсутствующие данные.

| Блок | Содержимое | Стадии |
| --- | --- | --- |
| `<spec>` | Текст снимка ТЗ с номерами строк `NNN│ text` | extract, findings, questions, chat |
| `<previous_requirements>` | `[{id, text, section}]` прошлой версии | extract (re-audit) |
| `<requirements>` | `[{id, text, kind, section, line_start, line_end}]` | findings, questions, decompose, next/context (только `T.requirements`) |
| `<summary>` | `{feynman, in_scope, out_of_scope}` | findings, decompose |
| `<repo_context>` | `{stack, test_framework, tree (обрезанное), conventions[], key_files[{path, role, excerpt}]}` — собирает CLI эвристиками | findings, questions, decompose, chat |
| `<decisions>` | `[{id, kind, text, closes[], option}]`, только актуальные | findings (re-audit), decompose, next/context |
| `<existing_findings>` | `[{id, kind, requirements, title, quote, status}]` | findings (re-audit) |
| `<existing_questions>` | `[{id, text, findings, status}]` открытые | questions |
| `<findings>` | открытые `A` без открытого `O` | questions |
| `<open_items>` | `[{id, type: A\|O, severity, audience?, requirements, text}]` | decompose |
| `<existing_blocks>` | `[{id, kind, title, requirements, decisions}]` | decompose (update) |
| `<existing_tasks>` | `[{id, status, title, block, requirements, order}]` | decompose (update) |
| `<task>` `<block>` | `T` и её `B` | next/context |
| `<repo_tree>` `<task_files>` `<candidates>` | листинг; содержимое `B.files`; 3–6 файлов-кандидатов | next/context |
| `<state>` | проекция: summary + все объекты в одну строку каждый | chat |
| `<focus>` | объект и все связанные (`O2` → его `A`, их `R`, evidence, `D`, `T`, где он в `blocked_by`) | chat |
| `<history>` | предыдущие ходы `[{role, content}]` | chat |
| `<state_delta>` | `«since 2026-09-22: O2 → answered (D4); +T1..T9»` | chat (resume) |

Размер: `<spec>` целиком; `<repo_context>` — бюджет (например, ≤ 8k токенов), CLI режет по приоритету: конвенции → ключевые файлы → дерево.

---

## 7. Пост-валидация (Python, до записи)

Ошибка (exit 1, состояние не меняется):

- ответ не проходит схему;
- ссылка на несуществующий id; `key` без объекта; цикл в `depends_on`;
- `A` без `requirements` или `evidence`; `quote` не найдена в снимке (допуск — нормализация пробелов);
- `O` без `findings` (кроме `--question`); `option.basis.ref` указывает на несуществующий `R`/файл;
- `T` без `requirements`; `matches` на объект другого типа или статуса `done` (для `T`);
- `blocked` не-null при непустом payload.

Неопределённость (не ошибка, записывается как есть):

- `confidence: low`;
- `uncertainties` в `decompose` / `next`;
- `uncovered` требования;
- `O` без options;
- `blocked` стадии — печатается пользователю с подсказкой, что закрыть.

---

## 8. Примеры

### 8.1 `hz audit docs/spec.md` (первый запуск)

```text
CLI:   читает файл → снимок .hz/spec/9c1e.md → нумерует строки

call 1  system = common/system.md + common/model.md + audit/extract.md
        user   = <spec>…</spec>
        schema = audit/schema/extract.json
        →  { requirements: [{text, kind, section, line_start, line_end, matches: null}, …37],
             removed: [], summary: {feynman, in_scope, out_of_scope} }
CLI:   R1..R37, пишет state

call 2  system = … + audit/findings.md
        user   = <spec> <requirements> <summary>
        schema = audit/schema/findings.json
        →  { findings: [{key:"f1", matches:null, kind:"inconsistent", severity:"blocker",
                         requirements:["R7","R19"], evidence:[{142..142,"…"},{301..301,"…"}], …}, …11] }
CLI:   A1..A11; проверяет quotes по снимку

call 3  system = … + audit/questions.md
        user   = <spec> <requirements> <findings (open A)> [<repo_context>]
        schema = audit/schema/questions.json
        →  { questions: [{key:"q1", matches:null, text, why, audience:"business",
                          findings:["A1"], options:[{A,…,basis:{spec,R7,"…"}},{B,…,basis:{spec,R19,"…"}}]}, …6] }
CLI:   O1..O6; severity(O) = max(A); рендер audit.md; сводка
```

### 8.2 `hz audit O2 --answer "A"`

```text
CLI:   LLM не вызывается. D1{kind:answer, closes:[O2], option:"A"}; O2.status=answered;
       A3.status=resolved(by D1); лог; рендер audit.md.
```

### 8.3 `hz audit docs/spec_v2.md`

```text
call 1  extract  + <previous_requirements>    → matches/removed
call 2  findings + <existing_findings> <decisions>  → matches; A(inconsistent, evidence:[{decision:D3},{lines}])
call 3  questions + <existing_questions>       → matches
CLI:   сопоставление, resolved(spec_changed), дельта в консоль
```

### 8.4 `hz decompose --repo .`

```text
CLI:   repo_context = {stack: rails, test: rspec, tree, conventions, key_files}

call    system = common/* + decompose/prompt.md
        user   = <summary> <requirements (active, 34)> <decisions (D1, D6)> <open_items (O4 high…)> <repo_context>
        schema = decompose/schema.json
        →  { blocks: [{key:"b2", kind:"job", title:"PaymentJob", requirements:["R21","R22"],
                       decisions:["D4","D6"], contract, files:[…]}, …],
             tasks: [{key:"t5", block:"b2", order:5, title, goal, requirements:["R21","R22"],
                      depends_on:["t3","t4"], blocked_by:[], done_when:[…], notes:[]},
                     {key:"t7", …, blocked_by:["O4"]}, …],
             uncertainties: [{finding:{key:"f1",…}, question:{key:"q1", findings:["f1"]}, affects:["t6"], blocking:false}],
             uncovered: [], skipped: [{requirement:"R11", out_of_scope:"Версионирование тарифов"}] }
CLI:   B1..B6, T1..T9; A15, O10 (origin: decompose); рёбра; проверка графа; рендер
```

### 8.5 `hz next --prompt`

```text
CLI:   выбирает T5 (T.ready) — без LLM; поднимает B2 по T.block
       candidates = файлы рядом с B2.files

call    system = common/* + next/context.md
        user   = <task T5> <block B2> <requirements R21 R22> <decisions D4 D6> <repo_tree> <task_files> <candidates>
        schema = next/schema.json
        →  { example_files:[{path:"app/jobs/job_base.rb", why:"retry config pattern"}],
             conventions:[{rule:"jobs inherit JobBase", file:"app/jobs/job_base.rb"}],
             approach:["…per D1…", …], already_done:[], uncertainties:[] }
CLI:   рендер next/handoff.md → stdout
```

### 8.6 `hz chat O4 --persona columbo`

```text
CLI:   focus = O4 + A7 + R24 + T7(blocked_by O4)

call    system = common/* + chat/prompt.md + chat/personas/columbo.md
        user   = <spec> <state> <focus> <history> + "в проекте все алерты идут в Sentry"
        schema = chat/schema.json
        →  { kind:"proposal",
             reply:"Понял. Тогда одна деталь: R24 говорит «уведомляет команду»…",
             references:["O4","R24","A7"],
             proposals:[{action:"assume", target:"O4",
                         text:"Sentry, как все алерты проекта; команда — через on-call",
                         rationale:"технический вопрос; основание — конвенция репозитория"}] }
CLI:   печатает reply; показывает карточку «≡ hz audit O4 --assume "…" [y/N]»; по y — тот же код, что флаг
```

---

## 9. Открытые вопросы

1. **Стадия 2 одним вызовом или по `kind`.** Один вызов дешевле и проще сопоставлять; пять вызовов (по одному на `kind`) точнее на больших ТЗ. Промт `findings.md` не зависит от выбора — CLI может передать подмножество kinds в отдельном блоке `<kinds>`; пока не добавлен.
2. **Стриминг чата.** Структурированный ответ не стримится. Альтернатива: текст стримом + завершающий блок ```` ```hz-proposals ```` с JSON. Выбрано структурированное — единообразно с остальными стадиями; если задержка будет мешать, переключить только `chat`.
3. **`--question` без LLM.** `audience` ручного вопроса: флаг `--audience`, вопрос в консоли или дефолт `technical` (раз задаёт разработчик)? Пока — дефолт `technical`, меняется через `hz chat` не нужно.
4. **Бюджет `<repo_context>`** и эвристики сборки (какие файлы — «ключевые») — детали реализации, но они влияют на качество `findings` (подавление) и `decompose` (files). Стоит зафиксировать после первых прогонов.
