# Автономная локальная поставка

PyApp 0.30.0, CPython embeddable 3.11.9 x64, Inno Setup. PyInstaller не используется. Конечному пользователю не требуется Python или uv; uv нужен разработчику.

Подготовка runtime и реальный локальный синтез через Native Messaging проверены на текущем Windows-компьютере при пустом PATH. Сборочные инструменты теперь подготовлены в `.tools`: Rust/Cargo 1.90.0 GNU, w64devkit 2.5.0 и portable Inno Setup 6.7.4. Их загрузки проверены SHA-256, подпись издателя Inno Setup подтверждена. Статус фактической сборки и приёмки указан в HANDOFF.md; наличие компилятора само по себе не означает готовый установщик. Чистая Windows не проверялась. Без установленных проверенных голосов компонент сообщает `ready:false`.

Последний проверенный runtime: `build/local-voices-runtime-04` (обновлённые status.selected и прогрев двух голосов перед call-ready). Smoke встроенного Python с английским голосом прошёл; модели хранятся отдельно. Старые runtime-каталоги не обновляются автоматически. Staging расширения включает аудиоклиент, стенограммы и `licenses/legacy-MIT.txt` по явному списку файлов.

Настоящий PyApp exe и Inno-установщик **собраны и проверены на текущей Windows**. Файлы: `build/local-voices-runtime-04/CallTranslatorLocal.exe` и `build/installer-stage-01/installer-output/CallTranslatorSetup.exe`. Пройдены first-boot stdio/синтез, установка/удаление и отдельное настоящее Chrome connectNative/озвучивание в временном профиле. Отчёты соответственно в prepared, `build/installer-smoke-01` и `build/chrome-native-smoke-03`. Чистая Windows и полный Meet остаются непроверенными; сборка не подписана.

## Подготовка

Официальный URL и SHA-256 загруженного runtime закреплены в `tools/runtime-lock.json`. Этот хеш зафиксирован после загрузки с python.org по HTTPS, отдельная проверка подписи издателя не выполнялась. Runtime лежит в игнорируемой `.tools`, подготовленный архив — в `build`.

```powershell
uv run --frozen python -m tools.prepare_local --runtime .tools/python-3.11.9-embed-amd64.zip --sha256 009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b --output build/local-spike-01
uv run --frozen python -m tools.smoke_local_runtime build/local-spike-01
```

Подготовка принимает только ожидаемую структуру runtime, проверяет хеш и сохраняет Python LICENSE.txt. В архив добавляется только новый `call_translator_local`, без серверных credentials, моделей, окружений и файлов персонального проекта. `_pth` включает встроенный каталог пакета. Настройки PyApp: `DISTRIBUTION_EMBED=1`, `FULL_ISOLATION=1`, `SKIP_INSTALL=1`, выполнение модуля `call_translator_local`. Поэтому установочные обращения к PyPI в этой конструкции не требуются. Это ещё нужно подтвердить при первом запуске PyApp-exe, включая чистый stdout для Chrome.

Smoke запускает `python.exe` подготовленного runtime с пустым PATH, проверяет self-test и двоичный обмен Native Messaging. Это не тест на чистой Windows, не сборка PyApp и не проверка синтеза.

Для runtime с синтезом сначала подготовить группу `local` из lock-файла. Это staging зависимостей, не копирование venv. Модели голосов не встраиваются, публичный ключ каталога встраивается.

```powershell
uv run --frozen --group local python -m tools.build_local_dependencies
uv run --frozen --group local python -m tools.prepare_local --runtime .tools/python-3.11.9-embed-amd64.zip --sha256 009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b --output build/local-voices-runtime --dependencies .tools/local-dependencies
uv run --frozen --group local python -m tools.smoke_local_runtime build/local-voices-runtime --voice-root build/local-voices --voice-id uk-basic
```

Последний вариант smoke действительно проверяет загрузку библиотек и синтез из встроенного Python с пустым PATH, используя отдельно установленный новый голос. Никакого вывода в аудиоустройство он не выполняет. Имена build-каталогов задавать новыми: подготовка не перезаписывает существующие результаты. После изменения исходников компонента нужно подготовить новый runtime. Детали подписей, файлов и лицензий — в `docs/VOICES.md`.

## Сборка и упаковка

На Windows build-машине инструменты можно подготовить изолированно, без изменения системного PATH. Версии и хеши закреплены в `tools/build-toolchain-lock.json`. Bootstrap использует прямой менеджер Rustup, GNU toolchain с собственным linker, portable GCC для C-зависимостей и portable Inno. Если изменился скачиваемый Rustup, проверка закреплённого хеша завершится ошибкой; нельзя незаметно обновлять lock.

```powershell
powershell.exe -NoProfile -File tools/bootstrap-build.ps1
powershell.exe -NoProfile -File tools/build-local.ps1 -PreparedDirectory build/local-voices-runtime-04
uv run --frozen python -m tools.smoke_pyapp build/local-voices-runtime-04 --voice-root build/local-voices --voice-id en-basic
uv run --frozen python -m tools.extension_id
```

Публичный `key` в `extension/manifest.json` закрепляет ID распакованного расширения независимо от пути установки. Это публичная идентичность нового расширения, не секрет авторизации; приватный ключ не сохранялся. Не перегенерировать его при обновлении. Нельзя использовать ID персонального расширения.

`tools.smoke_pyapp` проверяет настоящий exe, начиная с первого framed stdin/stdout запуска в новом временном runtime-каталоге. PATH пустой, HTTP/HTTPS proxy направлен на закрытый localhost-порт, серверные секреты не наследуются. Дополнительно проверяется настоящий синтез выбранного установленного голоса. Общий пользовательский distribution cache PyApp не изолируется и не удаляется: PyApp может сохранить там собственный встроенный архив и lock. Поэтому это не проверка полностью пустого профиля/сети и не чистая Windows. Сохраняется отчёт с хешем exe.

`tools.stage_installer` принимает подготовленную директорию, этот ID, файл обязательной лицензии PyApp и новую выходную директорию. Требует успешную сборку, self-test, хеш PyApp-exe и соответствующий этому хешу успешный first-boot Native Messaging smoke. Включает только новый бинарник, выбранные файлы расширения, Native Messaging manifest, Python/PyApp лицензии и читаемые уведомления зависимостей из runtime.

```text
uv run --frozen python -m tools.stage_installer --prepared build/local-spike-01 --extension-id <NEW_EXTENSION_ID> --pyapp-license <PYAPP_LICENSE_PATH> --output build/installer-stage-01
ISCC /DStageDir=<ABSOLUTE_STAGE_DIRECTORY> installer/CallTranslator.iss
```

Обёртка `tools/compile-installer.ps1` выполняет staging и компиляцию, сохраняет SHA-256/размер установщика и отдельные непроверенные статусы:

```powershell
powershell.exe -NoProfile -File tools/compile-installer.ps1 -PreparedDirectory build/local-voices-runtime-04 -StageDirectory build/installer-stage-01 -PyAppLicense .tools/build-toolchain/PyApp-and-dependencies-NOTICES.txt
powershell.exe -NoProfile -File tools/smoke-installer.ps1 -StageDirectory build/installer-stage-01 -OutputDirectory build/installer-smoke-01
```

Smoke установщика временно регистрирует **новый** SaaS host в HKCU, проверяет его manifest/файлы и удаляет собственную тестовую установку. Он отказывается заменять существующую SaaS-установку в обоих registry views. Целевая папка должна быть новой внутри build проекта; старый host не читается/не меняется. Это тест установки/удаления, не Chrome connectNative и не чистая Windows.

Для отдельной Chrome-проверки: `npm install --prefix .tools/browser-qa --no-audit --no-fund --ignore-scripts playwright@1.56.1`, затем `powershell.exe -NoProfile -File tools/smoke-extension-native.ps1 -StageDirectory build/installer-stage-01 -OutputDirectory build/chrome-native-smoke-NEW`. Это тоже временная регистрация exact SaaS host с отказом при существующем ключе и удалением только собственной записи. Используется установленный Chrome, отдельный временный профиль, стандартное окружение Windows без серверных credentials и модели из build. Постоянная установка в пользовательский Chrome не выполняется. Архивный installer-manifest содержит статусы на момент компиляции; поздние QA результаты находятся в отдельных отчётах.

`tools.collect_build_notices` собирает оригинальные LICENSE/COPYING/NOTICE из доступных Cargo-пакетов, перечисленных в закреплённом Cargo.lock PyApp, и сохраняет отдельный отчёт. Для пакетов без таких файлов сохраняется README и фиксируется fallback; недоступные записи lock перечисляются отдельно. Текущий инвентарь содержит 196 доступных пакетов, три README fallback. Это помощь сохранению уведомлений, а не завершённая юридическая приёмка. Исходный README PyApp и выбранный полный Apache-2.0 текст сохранены; перед публичной раздачей остаются проверка всех уведомлений и требования соответствующих исходников GPL/LGPL.

Установка идёт в `%LOCALAPPDATA%\Programs\CallTranslatorSaaS`, без администратора, Windows 10+ x64, с host `org.call_translator.saas.local` в HKCU. Manifest использует разрешённый относительный путь к exe. Группа меню и uninstall-запись названы Call Translator SaaS. Автоматическое закрытие/перезапуск приложений установщиком отключены: перед обновлением нужно завершить звонок и закрыть расширение. Chrome требует ручной загрузки расширения в режиме разработчика; инструкция открывается отдельно. Порядок реального теста — в [FIRST_CALL.md](FIRST_CALL.md).

До выпуска: собрать настоящий PyApp, подтвердить первый офлайн-запуск на чистой Windows без Python/PyPI, проверить stdout Chrome, загрузить расширение и Native Messaging, закончить подбор/приёмку голосов обоих направлений, лицензии и необходимые исходники GPL/LGPL-компонентов, обновления самого компонента с откатом. Подписанный каталог и безопасная установка/смена голоса уже реализованы, но полный звонок ещё не проверен. Перед публичной поставкой нужна подпись исполняемых файлов и установщика.

Источники: [PyApp distribution](https://ofek.dev/pyapp/latest/config/distribution/), [skip install](https://ofek.dev/pyapp/latest/config/installation/), [build](https://ofek.dev/pyapp/latest/build/), [release 0.30.0](https://github.com/ofek/pyapp/releases/tag/v0.30.0), [Chrome Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).
