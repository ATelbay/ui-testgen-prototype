# Данные

## data/snapshots

Восемь XML-дампов `adb shell uiautomator dump` экранов системного приложения
Settings (`com.android.settings`). Они служат реалистичной нагрузкой для
микробенчмарка проверки локаторов.

| Параметр | Значение |
| --- | --- |
| Устройство | эмулятор Android, профиль `sdk_gphone16k_arm64`, Android 17 (API 37) |
| Образ | `system-images;android-37.1;google_apis_playstore_ps16k;arm64-v8a` |
| Способ | `benchmarks/capture_snapshots.py`: `am force-stop`, запуск intent, ожидание 5 с, дамп |
| Экраны | settings_main, wifi, bluetooth, security, display, sound, date_time, accessibility |
| Дата снятия | 16.11.2026 (UTC — в `results/macro/device.json`) |

Эмулятор запускался в режиме `-read-only`, учётные записи в нём не
использовались. Перед добавлением дампы проверены на наличие персональных
данных. Экран списка приложений исключён, так как он показывает
приложения, установленные на конкретном AVD.

Дампы содержат тексты интерфейса Android и Google Settings. Эти материалы
не принадлежат автору и не распространяются по лицензии MIT. Они включены
только как входные данные измерений. При публикации допускается заменить их
инструкцией по повторному снятию: `scripts/reproduce.sh --capture`.

## tests/fixtures

`login.xml` — синтетический дамп экрана входа, созданный автором для
модульных тестов.
