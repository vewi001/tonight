# Отдельное обновление каталога — ход работы

09.10.2026: цель активна, полная функция НЕ завершена и НЕ опубликована.
Пользовательская готовая portable остаётся 1.6.5 с обновлением приложения.

## Контракт и решения

- FEATURE_SPEC_CATALOG_UPDATE.md: JSON-проекция вместо распространения личной
  SQLite; независимые версии каталога; min_app_version; безопасные manifests.
- Пользователь подтвердил политику исправлений: сохранять личные изменения;
  изменять поле лишь если оно совпадает с baseline прошлого пакета. Старые
  заполненные значения без baseline не переписывать. Слияние реализовано и проверено.
- AGENTS.md в исходной папке/предках не найден. Изначально только внутренний
  AUTO_UPDATE_PROGRESS.md был untracked. Старые задачи автообновления не повторялись.
- Read-only исследование catalog_merge_research (gpt-6-luna/Low, fork none)
  завершено. Текущий bootstrap upsert по id и COALESCE недостаточен для нового
  независимого обновления: нужны сопоставление tmdb_id, проверка конфликтов,
  стабильный локальный id и согласованная установка медиа/базы.

## Завершённый срез 1

- backend/catalog_package.py: builder и reader формата 1, только явно разрешённые
  поля; нормализованные списки JSON; ограничения типов, id, tmdb_id, трейлеров.
  Unknown/private поля входящего пакета отклоняются, приватные поля источника
  не читаются и не экспортируются. Источник SQLite открывается mode=ro.
- Проверяются состав ZIP, case-insensitive дубликаты, Windows paths/devices,
  symlinks/encryption, размер самого архива и распакованного содержимого,
  SHA-256 и размер каждого файла. Нет SQL/DDL/пользовательской SQLite в пакете.
- scripts/build_catalog_package.py: обязательные source-data/output/version/
  min-app-version; optional created-at для воспроизводимости. По умолчанию
  только метаданные. Media требует include-media + media-rights-reviewed;
  это заявление автора о проверке, а не предоставление лицензии.
- Временный ZIP сначала полностью проверяется; hardlink публикует его без
  перезаписи даже при появлении конкурентного файла. Файловая система вывода
  должна поддерживать hardlinks (проверено на Windows NTFS). Медиа пишутся
  потоково, а не целиком в память. Existing output и invalid source дают CLI exit 1.
- Tests-first: первый запуск упал при отсутствии модуля. Затем 11 тестов прошли;
  добавлены отрицательные случаи с пересчитанным digest, типами tmdb_id/year,
  NaN, private fields, unsafe id, ZIP-link и фактическим размером архива.
- Короткий read-only review выполнен тем же субагентом после завершения исследования.
  Утверждения про отсутствие проверки типов tmdb_id и необязательный movies.json
  не подтвердились кодом/тестами. JSON ограничен 32 МиБ; весь ZIP — 500 МиБ.
  Добавлены предел самого файла ZIP и Windows-device id. Защита родительских
  путей установки остаётся отдельной обязанностью будущего consumer; CLI —
  инструмент автора, а не сетевой маршрут записи произвольных путей.
- CLI smoke на обезличенном каталоге verified portable: 649 карточек, media=0,
  263541 байт. work/catalog-contract-smoke/Tonight-catalog-1.0.0.zip.
  created_at=2026-10-09T12:00:00Z; min_app_version=1.6.6.
  Это тестовый пакет контракта, не публичный релиз и не совместимый пакет для 1.6.5.
- Повторный CLI запуск с тем же output безопасно вернул exit 1.
- Финальный full pytest: 223 passed (17.85 с); node --check frontend/app.js
  и git diff --check прошли. UI/API/миграции не менялись; браузер и EXE не
  пересобирались, установки каталога пока нет. Проверочные серверы не запускались.

## Следующий безопасный срез

### Чистая политика сохранения личных правок

- backend/catalog_merge_policy.py: plan_field_updates не пишет в SQLite/файлы,
  принимает уже identity-matched, validated, normalized JSON-значения.
  Возвращает отдельные changes и baseline; будущий installer обязан сохранить
  их вместе в одной транзакции после проверки идентичности.
- Управляемое нетронутое поле исправляется. Личное отличие/очистка сохраняется.
  Старое заполненное поле без baseline не присваивается источнику; только NULL
  можно заполнить и начать отслеживать. Missing/NULL provider не очищают поле
  и не меняют прежний baseline. id/tmdb_id не попадают в field patches.
  Входящие unknown поля отклоняются; private поля current/baseline не входят
  в результат. Inputs и вложенные списки не мутируются.
- 11 tests-first сценариев: initial module missing, затем зелёные. Отдельный
  короткий read-only обзор catalog_merge_research (Luna/Low) не выявил реальных
  дефектов в границах pure planner. Его preconditions остаются обязанностью
  будущего consumer: SQLite JSON надо нормализовать, identity подтвердить.
- Последний полный pytest: 243 passed (19.94 с), node/diff check прошли.
  UI/API/миграции и готовые EXE не менялись, серверы не запускались.
- Начальный остаток продолжения: 16% окна. Это ограниченный чистый helper,
  не новый крупный этап и не завершённая установка каталога.

### Небольшое усиление после среза 1

- Два отрицательных теста сначала воспроизвели приём JSON с повторяющимися
  ключами version/id даже при корректном digest. Reader теперь отклоняет
  повторяющиеся ключи на всех уровнях манифеста и карточек.
- read_catalog_package получил keyword app_version: совместимость проверяется
  численно; более старый клиент отклоняется до передачи данных установщику.
  Семь tests-first случаев сначала упали, затем прошли. Версии ограничены
  32 символами. Сборщик читает будущий пакет без app_version; будущий consumer
  обязан передавать реальную версию приложения, не обходить этот gate.
- Последний полный pytest: 232 passed (18.93 с), node/diff check прошли.
  Реальный тестовый пакет с 649 фильмами принят для 1.6.6 и отклонён для
  1.6.5: work/smoke_catalog_compatibility.py. Серверы не запускались.
- Начальный остаток этого продолжения: 19% окна; крупное слияние/интерфейс
  не начинались. Совместимость на уровне чтения завершена, но подключение
  к настоящему установщику остаётся частью следующих срезов.

1. Тестами определить совместимость пакета и транзакционное слияние: все
   персональные таблицы/ссылки, canonical tmdb_id, конфликт id, повторы,
   baseline управляемых полей, сохранение локальных правок.
2. Решить согласованную установку DB/media и recovery при сбое/следующем запуске;
   не переносить потенциально частичную операцию bootstrap в сетевую установку.
   Проверять junction/symlink каждого целевого пути; проверить реальное декодирование
   медиа и приватные EXIF/нежелательные метаданные до готовности распространения.
3. Затем GitHub catalog-vX.Y.Z (не app Latest), downloader/manager/shared lock,
   localhost-only API, экран каталога и проверенные версии/даты.
4. Browser и isolated portable smoke успеха/ошибок и сохранности данных; затем
   сборка новой версии приложения. Публикация только после нового подтверждения.

## Проверенный preflight идентичности — точка продолжения

- backend/catalog_identity.py: чистое сопоставление source id -> local id.
  tmdb_id имеет приоритет; совместимый id и original_title/title + год — fallback.
  Разные известные tmdb_id не объединяются по названию. При конфликтах,
  неоднозначности и нескольких карточках на один фильм весь preflight отклоняется.
  Входные данные не меняются; SQLite, история и файлы пока не затрагиваются.
- 15 исходных tests-first сценариев прошли; полный pytest: 258 passed (18.53 с).
  Короткий независимый обзор Luna/Low обнаружил whitespace original_title:
  пустая после trim строка не использовала title, что давало дубль/ложное совпадение.
  Два новых регрессионных теста сначала упали; fallback после trim исправлен.
- Финальный полный pytest: 260 passed; node --check frontend/app.js и
  git diff --check прошли. Серверы не запускались; браузерные и portable-проверки
  остаются обязательными после появления настоящего consumer/UI.
- Следующий шаг: транзакционный installer с baseline и stable-id mapping,
  согласованной установкой DB/media, backup/recovery и общей блокировкой.
  Затем API/UI/GitHub discovery; цель целиком по-прежнему не завершена.

Последний остаток квоты: 10% окна, 27% недели; сброс 09.10.2026 23:49:01 МСК.
Сохранена безопасная точка продолжения; новых крупных этапов не начинать.
Проверенные исходники синхронизированы; .env/.venv/data и готовые EXE не менять.

## Транзакционное слияние карточек — 09.10.2026

- Пользователь попросил продолжать до исчерпания окна, сняв порог остановки 10%.
  Бесплатный reset не использовался. Начальный остаток 9%, после среза 8%.
- backend/catalog_database.py: merge_catalog_movies использует caller-owned
  BEGIN IMMEDIATE и SAVEPOINT; валидирует вход, сопоставляет весь пакет,
  нормализует SQLite JSON, сохраняет metadata и catalog_field_baselines вместе.
  Новый tmdb_id добавляется только отсутствующему при однозначном совпадении.
  Нет REPLACE/DELETE, изменения локального id или коммита чужой транзакции.
- 9 tests-first проверок: новое заполнение/baseline, внешняя отмена, правки
  пользователя, legacy-поля, заполненные персональные таблицы и app_meta,
  ошибки до и в середине записи, повтор, NULL/omitted поля и повреждённый JSON.
  SQL-триггер проверяет откат как новых строк, так и уже обновлённых baseline.
- Полный pytest: 269 passed (25.02 с); node --check и git diff --check прошли.
  Независимый Luna/Low review не выявил дефектов с потерей данных. Его замечание
  о валидации до SAVEPOINT не требует изменения: до savepoint записей нет.
- Это внутренний DB-helper, НЕ полный installer. Не подключён к live API,
  пользовательской базе или media; версия/дата установки не изменяются.
  Нужны общая блокировка, backup/recovery и согласованное применение DB/media.
  Готовые EXE по-прежнему 1.6.5, браузер/portable smoke ещё впереди.

## Read-only сводка каталога

- backend/catalog_status.py: количество фильмов, непустых обычных локальных
  постер-файлов, корректных YouTube links и пересечение этих двух признаков.
  Наличие файла не обещает декодирование картинки, link не обещает доступность видео.
  Generic art, пустые файлы, папки и symlink/junction не учитываются как постеры.
- Версия/дата только из двух разрешённых app_meta keys; отсутствующие или
  некорректные значения null, без выдуманной даты или версии приложения.
  Нет сети, записей, токена или путей в результатах. UI/API ещё не подключены.
- 4 tests-first сценария; full pytest: 273 passed (24.00 с), node/diff check
  прошли. Независимый Luna/Low review реальных дефектов не выявил.
- Последний измеренный остаток: 6% окна, 27% недели. Reset не использовался.

## Выбор и загрузка каталожного ZIP

- backend/catalog_discovery.py: отдельный чистый selector catalog-vX.Y.Z,
  численные версии, публичный stable релиз, один asset, точный repo/tag URL,
  размер/digest. Приложение /latest не менялось. 10 tests-first сценариев.
- При первом full run произошла интерференция общей autouse test DB из-за
  параллельного targeted запуска reviewer. Reviewer теперь НЕ запускает тесты;
  main повторил full последовательно: 283 passed (23.23 с), node/diff зелёные.
- backend/catalog_download.py: exclusive tempfile FD, точный источник,
  bounded HTTPS GitHub redirects, size/SHA-256, полный reader ZIP/manifest,
  version и обязательный app_version gate до публикации ZIP без overwrite.
  Existing files не считаются проверенными; ошибки убирают partial.
  Не извлекает/не устанавливает; caller обязан дать private staging dir и lock.
- 11 tests-first сценариев: success/redirect/no credentials, bad hash/length,
  version/compatibility, unsafe redirect/HTTP, non-ZIP с правильным SHA,
  existing output/unsafe asset path/link directory. Read-only Luna обзор
  реальных дефектов не выявил, тесты запускал только основной агент.
- Итоговый full pytest: 294 passed (23.84 с); node/diff check прошли.
- work/smoke_catalog_database.py: реальный обезличенный пакет 649 фильмов
  в изолированную временную SQLite; стабильный local id, история/оценка/
  watchlist/users сохранены, повтор без дубликатов, FK check чистый.
  Это DB smoke, НЕ end-to-end portable установка с медиа.
- Остаток 3% окна, 26% недели. Бесплатный reset не использован.
  Цель не завершена: installer/recovery/media, shared lock, discovery HTTP,
  manager, API/UI и browser/portable ещё требуются. Ничего не опубликовано.

## Последняя проверенная точка — HTTP discovery

- fetch_catalog_update: фиксированный публичный /releases, до 10 страниц по
  100 записей, без credentials/TMDB/environment proxy. Неполный список,
  rate limit, network/HTTP или malformed JSON не выдаются за отсутствие updates.
  Добавлено 6 tests-first случаев; reviewer только читал, тесты не запускал.
- Финальный полный pytest: 300 passed (24.08 с), node --check frontend/app.js
  и git diff --check прошли. Read-only Luna review дефектов не обнаружил.
- Все новые модули пока внутренние: не подключены к live маршрутам/пользовательской
  базе и готовой EXE. UI не менялся, серверы не запускались. Проверенные исходники
  синхронизированы в пользовательскую копию, .env/.venv/data не заменялись.
- Последний измеренный остаток: 1% пятичасового окна, 26% недели.
  Сброс 09.10.2026 23:49:01 МСК; reset не использован. Пользователь разрешил
  продолжать до исчерпания, но новая транзакционная установка/медиа/recovery
  не должна остаться частично подключённой к живым данным при обрыве лимита.
- Следующий полноценный этап: private staging + общая app/catalog блокировка;
  backup и согласованная DB/media установка с recovery, обязательная проверка
  decoded raster/metadata; version/date commit и защита повторной установки.
  Затем manager cache/states, localhost API, интерфейс, browser и isolated EXE.
  Цель целиком не достигнута, запускать текущую проверенную portable 1.6.5.

## Общая межпроцессная блокировка — 10.10.2026

- Окно сбросилось естественно: в начале 100%, бесплатный reset не использован.
- backend/update_guard.py: nonblocking OS lease на фиксированном
  .tonight-update.lock; Windows msvcrt/POSIX flock, проверка links/parents,
  безопасные ошибки, идемпотентное close. Marker остаётся, активность доказывает
  только OS lock. Проверены отдельные процессы и освобождение при os._exit.
- App UpdateManager получает lease перед скачиванием, держит в ready/installing,
  fail освобождает; второй manager/root или будущий catalog job не стартует.
- install_downloaded получает lease ПОСЛЕ ожидания старых PID и держит
  через apply/restart/rollback. Ручные update/rollback в updater.py также
  используют guarded wrappers. Low-level apply_release требует lease caller-а.
- Тест сначала воспроизвёл отсутствие installer guard; full затем выявил
  Windows PermissionError: rollback восстанавливал открытый marker-файл.
  Marker теперь в PRESERVED_NAMES; архив не может его заменить, snapshot и
  rollback его не трогают. Ошибка воспроизводилась и после фикса исчезла.
- Финальный full pytest: 310 passed (52.98 с), node --check frontend/app.js
  и git diff --check зелёные. Независимые read-only Luna обзоры выполнены;
  reviewer тесты НЕ запускал. Browser/новый EXE пока не проверялись: каталог
  не подключён к UI, новый portable не строился, 1.6.5 остаётся готовой версией.
- Проверенные исходники синхронизированы, .env/.venv/data не заменялись,
  тестовые серверы не запускались, публикации не было.
- Следующий этап: безопасный raster decoder (Pillow в .venv пока отсутствует,
  нужны pinned dependency и portable bundling), staging DB/media, backup и
  журнал recovery с commit версии/даты. После этого manager/API/UI и smoke.

## Проверка и очистка растровых медиа — 10.10.2026

- requirements.txt: Pillow==12.3.0; установлен только в рабочую .venv.
  Версия проверена по официальным release notes:
  https://pillow.readthedocs.io/en/stable/releasenotes/12.3.0.html.
  Пользовательская .venv не изменялась. Её source CLI требует установки
  обновлённых requirements; готовая portable 1.6.5 по-прежнему неизменна.
- backend/catalog_media.py: только JPEG/PNG/WebP, совпадающее расширение,
  один кадр, 16 МиБ bytes, 16 млн pixels, 8192 по стороне. Header/verify/full
  decode, orientation, свежая RGB/RGBA pixel-only картинка без EXIF/comments/
  ICC/XMP/text. PNG alpha сохраняется; не меняется глобальный MAX_IMAGE_PIXELS.
- Producer пишет только очищенные байты и считает их SHA/size, source не
  меняет. Чтобы не хранить весь каталог в памяти, очищает один файл на каждом
  проходе; если source изменился между hash/write, final reader отклоняет ZIP.
  Reader декодирует каждый raster entry с ограничением чтения одной картинки.
  Будущий installer тоже обязан sanitizer-ом подготовить bytes до размещения.
- 13 tests-first media случаев и 2 package регрессии (EXIF leak/fake image
  с правильным SHA) сначала подтвердили отсутствие защиты, затем зелёные.
  Portable builder явно включает 3 format plugins, тест аргументов не требует
  PyInstaller в обычной тестовой среде. Независимый read-only Luna review без
  реальных дефектов; pytest reviewer не запускал.
- Full pytest: 326 passed (24.66 с), node --check и git diff --check прошли.
- work/smoke_catalog_media_portable.py собран отдельным Windows onefile EXE
  с теми же hidden imports. Изолированная папка содержит только этот EXE;
  PASS JPEG/PNG/WebP, EXIF orientation и privacy. Проверено, что PIL и
  backend.catalog_media загружены из sys._MEIPASS, а не из внешнего Python.
  Это decoder smoke, НЕ end-to-end установка всего Tonight.
- Проверенные исходники синхронизированы; .env/.venv/data пользовательской
  копии сохранены. Серверы не запускались, публикации и нового Tonight EXE нет.
- Следующий этап не сокращён: installer с private staging/общим lease,
  backup, журналом созданных media и DB commit marker, recovery до старта UI,
  сохранением личных данных при любой фазе сбоя. Затем manager/API/UI и smoke.

## Внутренний установщик и восстановление — 10.10.2026

- catalog_install.py / catalog_recovery.py: общий native lease, приватная копия
  ZIP с size/SHA, повторная проверка manifest/min app, pixel-only staging,
  страховочная SQLite backup до merge, атомарный DB commit версии/даты/job marker.
  Локальные IDs сохраняются; существующие изображения любого расширения не заменяются.
- Journal публикуется fsync + replace до создания hardlinks. При незавершённой
  транзакции удаляются только собственные hardlinks с совпадающим hash; поздняя
  замена постера/изменение личных данных сохраняются. Старая DB автоматически
  не восстанавливается. После commit отсутствующее изображение восстанавливается
  из проверенного stage. Backup сохраняется; CatalogUpdates исключён из app ZIP.
- 14 installer/recovery tests, включая реальные дочерние os._exit в пяти фазах,
  повтор, несовместимость, ошибочный SHA, конкурентный постер, borrowed lease,
  замену постера после сбоя и восстановление после commit. Tests-first выявил
  отсутствие проверки совпадения расширений stage/target; исправлено, добавлена
  также граница суммарного размера журналированных медиа.
- Full pytest: 340 passed (37.98 с), node --check frontend/app.js и git diff --check
  прошли. Два read-only Luna review (recovery и installer), без запуска тестов.
- Это пока внутренний worker, не live API/startup/UI. Реальный power-loss и
  установка всего Tonight portable ещё не проверены. Серверы не запускались,
  новая сборка/публикация отсутствуют; готовая версия остаётся 1.6.5.
- Следующий шаг: manager с cache/throttle, состояниями и удержанием общего lease
  от скачивания до завершения recovery, затем startup/API/UI и isolated smoke.

## Внутренний координатор каталога — 10.10.2026

- CatalogUpdateManager: отдельная текущая catalog_version, безопасная публичная
  сводка состояния без путей/сырых исключений; cache 6 часов, manual throttle
  60 секунд. Ошибка check очищает старый offer. Recovery error запрещает новый
  job; recover можно повторить, локальные рекомендации не зависят от manager.
- Общий lease удерживается от reserve до завершения download/install/recovery;
  done только после возврата installer. Duplicate worker и старый reservation
  не могут занять повторную попытку либо освободить её lock. Tests-first replay
  воспроизвёл дефект; исправлен отдельной identity на каждой reservation.
- 9 tests, включая настоящий ZIP/manifest/image через HTTP MockTransport,
  download validator, DB/media installer и recovery: стабильный local ID,
  personal title/history, версия, локальный постер и очищенный journal.
  Сетевой доступ к GitHub в этом тесте отсутствует; это не browser/portable smoke.
- Read-only Luna review выполнен без тестов. Full pytest: 349 passed (45.30 с),
  node --check frontend/app.js и git diff --check зелёные, skip нет.
- CatalogDownloads исключён из app release ZIP; downloaded ZIP cleanup не
  откатывает уже выполненный commit. Пустые download job folders пока остаются.
- Остаток окна 79%, недели 23%; reset не использован. Серверы не запускались.
  Проверенные исходники синхронизированы; .env/.venv/data сохранены. Новой EXE
  и публикации нет. Запускать проверенную portable 1.6.5.
- Следующий безопасный срез: startup recovery ДО initialize/bootstrap/seed,
  localhost-only catalog status/check/install API и guards для восстановления
  пользовательских backup одновременно с catalog job. После этого UI/browser
  и end-to-end isolated Windows Tonight portable (успех/ошибки/personal data).

## Startup, локальные API и операции с личными данными — 10.10.2026

- main.py: startup recovery до initialize/bootstrap/seed. Ошибка recovery
  сохраняет доступность обычного вечера; catalog install запрещён до recovery.
  GET /api/catalog отдаёт summary/update без путей. POST check/install/recover
  защищены loopback client + localhost Host + action header + Origin.
  Телефон с корректным кодом вечера также не может управлять каталогом.
- Install отвечает 202 после reservation и запускает tracked to_thread worker.
  Lifespan shutdown ждёт реальный поток; отдельный тест доказывает ожидание
  заблокированного worker, а не просто отмену его asyncio wrapper.
- Create/restore/import backup и privacy delete используют общий lease и
  recovery перед изменениями. Corrupt journal оставляется, операции возвращают
  409 без изменения БД. Restore держит guard через initialize/bootstrap/seed.
- Installer backup перенесён в data/backups с job-specific prefix: штатная
  privacy delete теперь удаляет и catalog safety DB; movie catalog остаётся.
  Новые recovery helpers не исполняют SQL из архива и не восстанавливают старую
  базу поверх последующих личных изменений.
- Full suite выявил регрессию restore/delete для DB вне ROOT и fixture ROOT:
  когда pending journal отсутствует, обычные операции не требуют inside-root
  DB. Catalog manager показывает recovery_error для неподдерживаемого размещения,
  но import main/обычный вечер не ломаются. Регрессии исправлены, тесты зелёные.
- Luna read-only review выявил race создания backup с privacy delete; тест
  сначала подтвердил 200 при активном lease, затем fix дал 409. Reviewer тесты
  не запускал. Добавлены 14 новых API/data tests + два shutdown/journal случая:
  финальный full pytest 365 passed (38.30 с), node и diff зелёные.
- PRIVACY.md описывает фактические GitHub catalog requests и safety copies.
  Фронтенд пока не изменён, UI/browser и настоящий portable install остаются
  обязательными. Серверы не запускались, бинарники 1.6.5 не заменялись, публикации
  нет. Source CLI требует актуальные requirements; пользовательская .venv сохранена.
- Проверенные исходники синхронизированы, .env/.venv/data сохранены. Остаток окна
  73%, недели 22%; бесплатный reset не использован.
- Следующий шаг: отдельный экран «Каталог», понятные counts/version/date,
  отдельные app/catalog actions, polling состояния, safe errors/retry; Node UI
  behavior tests и браузерные сценарии на isolated fixture. Затем portable build,
  реальные install/recovery/error smoke и аудит полной цели. Не публиковать без
  отдельного подтверждения и не отмечать цель завершённой раньше этих проверок.

## Portable startup и подготовительная сборка — 10.10.2026

- Найден и tests-first исправлен запуск launcher: recovery раньше initialize/
  bootstrap/seed (две ветки idle/recovery_error). ASGI повторяет recovery
  идемпотентно. Независимый read-only Luna review: launcher порядок верный;
  замечание о внешней БД — известное fail-closed ограничение контракта, обычный
  вечер не блокируется, installs во внешнюю БД запрещены и покрыты тестом.
- Документированы правила catalog release: catalog-vX.Y.Z, точное вложение,
  size/digest, make_latest="false" как строка при create/publish draft; Latest
  остаётся app vX.Y.Z для совместимости с updater 1.6.5. Официальные GitHub REST
  docs проверены. Публикации не было. Пример min app 1.6.6 не обещает выпуск.
- Builder больше не удаляет старую work/portable-stage: создаёт уникальную
  staging папку внутри проверенного work. Regression test; старые файлы сохранены.
- APP_VERSION 1.6.6 — подготовительная, CHANGELOG Unreleased. README download
  всё ещё указывает опубликованную 1.6.5. Полный последовательный pytest:
  370 passed (31.60 с); node/diff зелёные. Между зелёными прогонами случайно
  запущены два pytest одновременно: их общая work/test-tonight.db конфликтовала,
  оба закончились; их результаты не приняты. Финальный прогон один, зелёный.
- Сборка успешно завершена: work/catalog-portable-1.6.6-check/
  Tonight-portable-1.6.6, portable ZIP 245629989 bytes, update ZIP 245635967 bytes.
  Production EXE, frontend/Pillow bundled; рабочие бинарники 1.6.5 не заменены.
- work/catalog_production_portable_smoke.py TEST ONLY запускает именно production
  Tonight.exe в mkdtemp копии: token empty, provider auto off, env/venv sentinels.
  Corrupt pending.json -> recovery_error, 649/644/571/568 counts; browser retry
  не выдаёт success, installs disabled, обычный экран настроения доступен,
  console errors []. Screenshot work/catalog-portable-recovery.jpg.
- Обычный production startup -> idle, те же counts. Browser реальный GitHub
  check -> «Новых пакетов каталога нет», console errors []. Screenshot
  work/catalog-portable-current.jpg. Кастомное имя в SQLite сохранено; старый
  frontend использует нейтральные фиксированные имена, это не новый дефект слияния.
  Final normal smoke session 28478 завершён Enter exit 0, owned exe stopped.
  Первый smoke 39693 завершён Ctrl-C exit 1; проверено отсутствие дочерних
  процессов по точному exe path/порта. Попытка input без PTY завершилась EOF,
  finally остановил EXE; принятый нормальный smoke повторён с PTY и exit 0.
- Проверенные исходники синхронизированы; user DB hash прежний, .env/.venv/data
  не менялись. Квота: 54% окна осталось, 19% недели; reset не использован.
- ОБЯЗАТЕЛЬНО ДАЛЬШЕ: аудит состава новых ZIP; install success/error в frozen
  whole-app fixture с fake GitHub transport и настоящими download/installer;
  настоящий process-crash journal + restart production EXE и личные history/
  feedback/watchlist/genre-exclusions/baselines сохранены. Не считать startup
  smoke доказательством полной portable установки. Затем app updater 1.6.5->1.6.6
  regression, rebuild при production changes, полный goal audit. Не публиковать
  и не заменять пользовательский EXE до полного этапа. Пока запускать portable 1.6.5.

## Экран «Каталог» и source browser smoke — 10.10.2026

- frontend/app.js: localhost-only nav/экран со всеми четырьмя counts, отдельной
  version/date и честными legacy/YouTube подписями. Отдельные catalog/app panels;
  catalog check/install/recover, guarded headers, progress, busy/ошибки, polling
  1.5 с active / 30 с open screen, stale status responses отсекаются request ID.
  Poll читает локальный API, не запускает GitHub discovery каждый раз. Панель
  обновляется без перерисовки текущего вечера. Cache app.js 3.6.0, CSS 3.4.1.
- Tests-first Node/vm contract: counts, legacy, escaping, available/downloading/
  recovery, local/remote isolation, отдельная app install button. Первое падение
  подтвердило отсутствие catalogPanel. Luna read-only review без дефектов и без
  запуска тестов. Browser выявил переполнение top-actions при viewport 561;
  regression test упал, добавлен flex-wrap; повтор DOM: width 561, scrollWidth 546.
- work/catalog_ui_smoke.py — TEST ONLY fixture, отдельные mkdtemp базы в work,
  TMDB token empty, auto TMDB off, GitHub MockTransport; реальный package reader,
  decoder, download и installer, не production backdoor. Совместимость пакета
  с текущим APP_VERSION, искусственный фильм и собственная orange картинка.
- Browser localhost 8782: исходно 72 / 0 poster / 0 trailer; check offer 1.0.0;
  click install -> downloading 0%, disabled buttons -> done, 73 / 1 / 1 / 1,
  catalog version/date зафиксированы, console errors []. Reload сохранил версию.
  Скриншот: work/catalog-ui-success.jpg (fullPage).
- Browser offline fixture 8783: error check без ложного current/success, counts
  неизменны, кнопка повторной проверки доступна; возврат к обычному home работает.
  Скриншот work/catalog-ui-offline.jpg. LAN 192.168.50.67:8783: ввод fixture code,
  второй зритель вошёл, nav/catalog/update controls отсутствуют. Это LAN smoke,
  не эмуляция конкретного телефона. API запрет с корректным code покрыт pytest.
- Full pytest после CSS fix: 367 passed (32.75 с), node и diff зелёные. Оба
  owned server sessions 17339/77211 остановлены Ctrl-C, вкладка закрыта. Чужие
  процессы не трогались. User env/venv/data сохранены при source sync.
- Полная функция ещё не готова: нужны new-version Windows portable build,
  end-to-end install/error/recovery с личными данными, дополнительные UI случаи
  несовместимости/recovery и итоговый requirement-by-requirement audit. Нет
  нового EXE/публикации, запускать опубликованную portable 1.6.5.
- Перед публикацией catalog release проверить, что он не становится app Latest
  (старый updater читает /releases/latest); закрепить make_latest=false либо
  совместимый безопасный fallback discovery. Не публиковать без подтверждения.

## Frozen whole-app install, recovery и app upgrade — 10.10.2026 (актуально)

- Предыдущий goal-turn — прогресс: launcher recovery regression, 370 tests,
  build и production startup/browser. Этот turn продолжает полную цель.
- work/audit_catalog_portable.py: оба 1.6.6 ZIP CRC + точный file allowlist,
  _safe_relative, flat raster media extensions, no ZIP symlinks, no env/venv/
  data/logs/backups. 1327/1328 entries. Read-only public seed: 649 movies,
  все персональные таблицы пусты, FK clean. Это аудит состава, не лицензия медиа.
- work/catalog_frozen_fixture.py TEST ONLY собран тем же PyInstaller builder
  с frontend и тремя PIL plugins в work/catalog-frozen-fixture-bin/
  TonightCatalogFixture.exe. Использует реальные launcher/main/catalog manager,
  discovery/download/ZIP/merge/install/recovery; подменён только httpx transport
  ответов публичного GitHub и app check. Токен пустой; Auth header запрещён.
  Fixture entry point не включён в production build/ZIP и не синхронизируется.
- work/run_catalog_frozen_smoke.py: mkdtemp isolated root, stable legacy local
  tmdb match + managed baseline/own edits + one new movie; personal tables,
  env/venv/data sentinel. Success -> done, новые медиа под stable local IDs,
  managed title исправлен, own overview/genres сохранены, FK clean, backup/journal.
  Hash mismatch/incompatible min app -> error, без новых movies/media/version.
- os._exit(73) в настоящем EXE на pre_commit/post_commit -> pending journal;
  restart именно production Tonight.exe -> idle. До commit rollback, после
  commit сохранён пакет; env/venv/data, личные строки, overrides/FK сохранены.
  Успешно повторены success/pre/post с JPEG+PNG+WebP в одном пакете (главный EXE
  декодирует все форматы, не только прежний decoder-only smoke).
- Luna read-only review нашёл два verification gaps, исправлены: snapshot теперь
  покрывает также sessions/participants/swipes/swipe_decks/weekly_picks; ZIP
  allowlist больше не принимает любые suffix paths с catalog/posters prefix.
  Сценарии повторены после усиления. Никаких production fixes по этим замечаниям
  не требовалось; тесты субагент не запускал.
- Browser frozen success session 56493: 74->75 movies, 0->2 posters, 0->1 trailer,
  catalog 1.0.0/date/done; во время download кнопки disabled, после success
  старая история My title/оценка доступны. Screenshot catalog-frozen-install-success.jpg.
  Browser incompatible session 34724: error, 74/0/0 unchanged, no version/date,
  история Октябрь 2026/My title/оценка сохранена, console errors []. Screenshot
  catalog-frozen-incompatible.jpg. Оба sessions Enter exit 0; вкладки закрыты.
  Первый history fixture использовал watched_at='now' и отображал undefined NaN;
  это исправлено в fixture на валидную ISO date, не production change.
- work/smoke_next_portable_update.py: именно установленный old 1.6.5 updater EXE
  + old Tonight.exe, новый production update ZIP. Helper handoff, old остановлен,
  1.6.6 перезапустилась; история/оценки/catalog_version 1.0.0/own description/
  env/venv/media/backup/rollback сохранены. Session 30334 exit 0, isolated
  work/app-update-1.6.6-35vrn7n_. Первая попытка fixture module import подменял
  port на 8771; исправлен reset env после import, собственные процессы той
  попытки остановлены по точному exe path. Не production regression.
- Реальный producer 649 карточек (без медиа, проверочный артефакт) дважды
  сформировал идентичные SHA-256 ZIP при фиксированных versions/UTC created_at:
  work/Tonight-catalog-1.0.0-metadata-check.zip и metadata-repeat.zip. Это не
  готовое публичное вложение и не разрешение публикации. Сами фильмы/видео
  не распространяются. Для media catalog нужен отдельный состав/rights review.
- Full pytest 370 passed (40.27 с), node/diff PASS. После этого менялись только
  test-only work helpers и progress docs, production исходники прежние.
  Проверка ports 8771/8784/8785/8786/8787/8788/8789: listeners нет; собственные
  процессы остановлены, чужие не трогались. Квота: 41% окна/17% недели осталось.
  Reset не использован. Source status uncommitted, публикации нет.
- ОСТАЛОСЬ: README.txt внутри 1.6.6 всё ещё от 1.6.5 — сделать version-aware
  build docs, regression test и обновить release artifacts. Проверить понятность
  error (сейчас hash/compatibility превращаются в общий совет connection/app
  update), при необходимости добавить безопасные typed reasons. Финальный
  requirement audit, авторская инструкция/реальный sanitized catalog candidate
  с явным решением по разрешённым media. Только затем синхронизировать verified
  EXE/каталог и запросить отдельное подтверждение публикации 1.6.6/catalog.
  Не отмечать цель complete по локальным mocks вместо настоящей публикации.
  Пока для обычного запуска использовать опубликованную portable 1.6.5.

## 10.10.2026 — реальные release candidates, конкретные ошибки и финальная регрессия

- Сделаны безопасные typed errors compatibility/integrity. Требуемая версия
  каноническая и ограниченная; произвольный текст исключений не выходит в UI.
  Несовместимый offer очищается и предлагает обновить приложение; при checksum
  ошибке остаётся возможность повторить загрузку. Lock освобождается в finally.
- Version-aware README.txt в portable builder и пять новых regression tests.
  Full pytest: 375 passed (42.70 с); node --check frontend/app.js и git diff
  --check PASS. Luna независимо проверила этот ограниченный срез: замечаний нет.
- Сборки заново сформированы в work/catalog-portable-1.6.6-ready:
  Tonight-portable-1.6.6.zip и Tonight-update-1.6.6.zip. Allowlist/CRC audit PASS,
  public seed 649 movies, личные таблицы пусты, FK clean. Fixture EXE также
  пересобран (work/catalog-frozen-fixture-bin-v2, только для тестов).
- Пользователь отдельно подтвердил проверку прав на включаемые изображения
  и разрешил ПОДГОТОВКУ пакета. Это НЕ подтверждение публикации и не юридическая
  проверка агентом. Производитель сформировал реальный пакет
  work/catalog-package-1.0.0/Tonight-catalog-1.0.0.zip, min app 1.6.6,
  created_at 2026-10-10T00:00:00Z: 649 карточек, 1287 очищенных изображений,
  размер 314265585 bytes. SHA-256:
  217c4c9e0b2681c952e786ecaa7a25013c8168c1152e3d871a090e44857d38bc.
  Это публичная JSON-проекция, не личная SQLite. Видео и сами фильмы не входят.
- Реальный пакет установлен без TMDB-токена в отдельном frozen whole-app
  экземпляре work/real-catalog-1.0.0-ofcp8wp1: done, версия 1.0.0/date,
  649 films / 644 local posters / 571 trailer links / 568 both. История, оценки,
  watchlist, exclusions, собственное описание, настройки, env/venv сохранены;
  snapshot backup создан, FK clean, pending journal удалён после commit.
- Browser 8790: первый экран готов, раздел Каталог показывает правильные
  counts/version/date/done; старая история и оценка доступны; поиск сохраняет
  собственное описание и показывает ссылки на трейлеры. Console errors [].
  Screenshot work/catalog-real-package-success.jpg. Доступность видео не
  проверена и так обозначена в UI; ссылки не обещают наличие видео.
- Browser 8786 (fresh v2): min app 9.0.0 показывает конкретный совет обновить
  Tonight; кнопки установки нет, старый каталог не изменён. Screenshot
  work/catalog-ready-incompatible.jpg; session 74049 PASS, exit 0.
- Fresh v2 hash PASS; реальные os._exit(73) pre/post commit с recovery именно
  production Tonight.exe PASS, сохранены все personal rows/env/venv/media/FK.
  Это обрыв процесса, НЕ физическое выключение компьютера.
- Старый опубликованный helper 1.6.5 -> свежий update ZIP 1.6.6 PASS:
  перезапуск, personal data/catalog version/overrides/env/venv/media/backup/
  rollback сохранены (work/app-update-1.6.6-akb25wzm, session 41409 exit 0).
  Все перечисленные собственные проверочные процессы остановлены.
- Отдельное подтверждение публикации кода и двух релизов запрошено. До ответа
  никаких push/tag/release/uploads не выполнять. После разрешения публиковать
  app v1.6.6 как Latest, catalog-v1.0.0 с make_latest="false", проверить digest,
  размер и public API, затем реальное обнаружение/загрузку без токена.
  Пока обычному пользователю запускать опубликованную 1.6.5; 1.6.6 — локальная
  проверенная кандидатная сборка, не выпущенная версия.
- Финальный аудит реальных трёх ZIP: CRC, состав, точный поиск локальных
  credential values без их вывода PASS. Контрольные суммы/размеры и критерии
  собраны в CATALOG_RELEASE_CHECKLIST.md. Проверенные исходники синхронизированы
  с пользовательской копией; .env/data DB hashes и .venv сохранены. Пользовательские
  EXE не заменены до финального release workflow. Listeners на проверочных
  ports 8771/8784-8790 отсутствуют. Квота: 30% окна, 15% недели; reset не использован.

## 10.10.2026 — публикация по отдельному подтверждению пользователя

- Получено явное разрешение опубликовать код/1.6.6/catalog 1.0.0 с изображениями.
  Git index audit: 51 source/test/doc files, локальных credentials нет; work/
  outputs/.env/.venv/data не включены. Full pytest повторён: 375 passed (45.87 с),
  node/diff PASS. Commit 4f85d46 отправлен в main; оба тега указывают на него.
- Опубликованы https://github.com/vewi001/tonight/releases/tag/v1.6.6 и
  https://github.com/vewi001/tonight/releases/tag/catalog-v1.0.0. Все три public
  asset names/sizes/SHA-256 совпадают с локальными проверенными файлами;
  draft/prerelease false. Latest API возвращает v1.6.6, каталог make_latest=false.
- Первое выполнение локального publish helper неудачно импортировало старый
  delivery script: его top-level --publish handler выполнил read-only audit/GET
  старой 1.6.5 и остановился на проверке исходного тега, до PATCH. Старые assets,
  release и tags не менялись. Новый helper автономен; успешная доставка exit 0.
- Production Tonight.exe без mock transport и с пустым токеном запущен в
  work/public-catalog-1.0.0-c75996oh, port 8791. Browser обнаружил публичный 1.0.0,
  install начал настоящий GET. Первые 16056320 bytes получены; проверка намеренно
  остановлена ДО установки. Полная онлайн-installation НЕ PASS. Отдельные
  ограниченные read-only probes HTTP200/206 получили ~397/618 KB за 30 секунд;
  начальная загрузка была медленной, позднее progress ускорился. Ни причины
  сети, ни постоянная скорость для других пользователей не установлены.
  Screenshot work/catalog-public-downloading.jpg. Session 45310 exit 1 ожидаемо
  на assert done после намеренного прекращения, finally остановил собственный EXE.
- Пользовательская Portable Tonight обновлена существующим helper до 1.6.6;
  helper exit 0 и API version 1.6.6 подтверждены, затем сервер 8792 остановлен.
  Первичный verification helper ошибочно сравнивал SELECT * старой/новой схемы
  и завершился после обновления на assert. Read-only audit со страховочной
  копией подтвердил: добавлены только sessions.selected_at/reconnect_count;
  ВСЕ исходные personal columns/rows/settings/FK сохранены. Это ошибка тестового
  сравнения схем, не потеря данных. Backup before-update-20261010-012926-462602.db
  и rollback/previous сохранены. Пакет не заменяет env/venv/data.
- Цель пока active: остаётся полная публичная загрузка/установка и подтверждение
  done/preservation после неё. Не перепубликовывать assets, не двигать теги.
  Для обычного запуска теперь пользовательская Portable Tonight/Tonight.exe 1.6.6.
  Квота: 20% окна/13% недели; reset не использован.

## 10.10.2026 — публичная end-to-end проверка завершена

- Предыдущий goal-turn классифицирован как progress: опубликованы код и оба
  релиза, обновлена пользовательская portable, подтверждены public digest/Latest.
  Тогда full public install оставался незавершённым; это не было completion.
- Перед повтором прочитан актуальный objective/checklist; Git чистый, прежние
  servers stopped. Запущен новый production Tonight.exe (без fixture/mock HTTP)
  в work/public-catalog-1.0.0-jigg71da, token пустой, port 8791. Check обнаружил
  реальный public catalog-v1.0.0; install полностью получил 314265585 bytes.
  Во время проверки 100% загрузки UI ещё не объявлял успех; далее installing,
  затем done после окончательной установки. Вторая загрузка была быстрее;
  предыдущая малая скорость не считается постоянной характеристикой продукта.
- Browser success: 649 films, 644 local posters, 571 trailer links, 568 both,
  catalog 1.0.0, дата successful update. Прежняя история/оценка отображаются;
  console errors []. Screenshot work/catalog-public-install-success.jpg.
- Driver session 42159 завершён Enter после done: PASS PUBLIC production catalog,
  реальные public GitHub download/install, сохранены история/ratings/watchlist/
  genre exclusions/own description/private setting/env/venv, FK clean, backup
  существует, pending journal удалён. Exit 0, OWNED PROCESS STOPPED. Проверка
  listeners 8771/8784-8792 пуста; вкладка закрыта.
- Producer повторно построил полный пакет из того же source data с фиксированным
  created_at и подтверждёнными media flags. Session 53126 exit 0. Полный ZIP в
  work/catalog-package-1.0.0-repeat/Tonight-catalog-1.0.0.zip имеет SHA-256
  217c4c9e0b2681c952e786ecaa7a25013c8168c1152e3d871a090e44857d38bc,
  идентичный опубликованному candidate; доказана reproducibility с media.
- Requirement audit CATALOG_RELEASE_CHECKLIST.md завершён: package/merge/safety/
  UI/API/backup/recovery/portable/public delivery доказаны. Production code не
  менялся после финального pytest 375 passed (45.87 с); node/diff PASS. Не
  утверждаем физическое отключение питания или доступность YouTube-видео.
- Финальные документы синхронизировать с пользовательской копией и отправить
  в main; assets и release tags не изменять. После проверки sync/servers можно
  завершить цель. Обычный запуск — Portable Tonight/Tonight.exe версии 1.6.6.
