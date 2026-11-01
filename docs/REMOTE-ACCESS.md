# SSH-MCP → home → игровой ПК (Bazzite)

> ВАЖНО: это проверенный **транспорт**, не доказательство готовности рендера. Перед любой работой читать [../AGENTS.md](../AGENTS.md) и [DEVELOPMENT-AND-TESTING.md](DEVELOPMENT-AND-TESTING.md). Состояние очередей/версий/сервисов обязательно проверять заново.

## Надёжный маршрут, проверен 2026-10-30

1. Через установленное SSH-MCP вызвать `infra_exec` с **`host="home"`**, **`as_root=true`**. SSH-MCP сам маршрутизирует запрос через VPS/OpenVPN на Ubuntu `xavoks-server`; не нужно пытаться вызвать `host="pc"` в SSH-MCP.
2. На home доступен SSH-ключ **`/opt/homeassistant/config/id_ed25519`** (не коммитить содержимое, не выводить его в отчёты). Он позволяет входить на Bazzite `192.168.50.27:22` как **`Xavok`**, регистр **строго** `Xavok`.
3. Проверенный read-only пример:

   ```bash
   ssh -i /opt/homeassistant/config/id_ed25519 \
     -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes \
     Xavok@192.168.50.27 \
     'hostname; id -un; date -Is; systemctl --user is-active mcp-vn-comfy mcp-vn-worker mcp-vn-vision; curl -sf http://127.0.0.1:8188/queue'
   ```

4. Ожидаемая идентичность — `xavok-pc` и `Xavok`. Критически важно: все три VN-службы — **пользовательские**; выполнять `systemctl --user status ...` внутри SSH-сеанса `Xavok`. Обычный `systemctl is-active` обращается к **system** и ошибочно показывает `inactive`. Проверять реальные unit ExecStart и runtime PID, а не статус по старому handoff.
5. На ПК `ComfyUI` слушает **127.0.0.1:8188**. Проверка `/queue`: оба массива `queue_running` и `queue_pending` должны быть пустыми перед запуском своего единственного GPU job. Очередь без задач сама по себе не исключает другого активного агента: проверять процессы, незавершённые systemd jobs и владельца очереди.
6. Локальная исследовательская директория владельца: `/var/home/Xavok/.local/share/mcp-vn/render-fix-20261030/`; здесь приватный `private-handoff-20261030.json` с исходниками, hash/paths и render evidence. **Никогда не коммитить этот manifest, изображения, prompts, save, токены и face refs.** Не делать `git clean`, reset, перезапись production или повторный GPU submit без проверки состояния.

### Пример вызова инструмента (псевдокод, без ключей)

```text
ssh-mcp.infra_exec(host="home", as_root=true,
  script="ssh -i /opt/homeassistant/config/id_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=yes Xavok@192.168.50.27 'systemctl --user is-active mcp-vn-comfy mcp-vn-worker mcp-vn-vision; curl -sf http://127.0.0.1:8188/queue'")
```

Если SSH отказывает, **не** использовать небезопасный `StrictHostKeyChecking=no` и не публиковать ключи. Проверить доступность ПК, SSH/known_hosts с home и обоснование расхождения. IP и путь к файлу являются деталями текущей установки, не универсальными настройками для чужого клона.


## Восстановление конкретной операции — 2026-11-01

Проверка оператора 1 ноября: основной SSH-MCP selftest прошёл на VPS/home. За 04:00–07:56 UTC audit зарегистрировал 848 завершённых команд без connector timeout; это не устанавливает причину конкретного отказа OpenAI. Не объявлять весь SSH недоступным по одному отклонённому payload и не считать `completed` доказательством результата.

| Фактическая ошибка | Следующее действие | Условие остановки |
|---|---|---|
| Подтверждённый timeout/refused соединения | До трёх повторов **read-only проверки соединения**, с реальными ожиданиями 10/30/60 секунд. После восстановления сверить исходную операцию; повтор не означает повтор мутации. | Восстановление, иная ошибка или исчерпанный бюджет. |
| Подтверждённый auth/reconnect | Поддерживаемое восстановление авторизации; после подтверждённого ремонта тот же ограниченный health check. Не выводить credentials. | Запрос подключения/подтверждения требует поддерживаемого пользовательского шага; общий permission error не доказательство auth. |
| `INVALID_ARGUMENT` | Сверить схему инструмента и исправить аргументы. Например `infra_file_read(action="read")`, не `action="text"`. | Не повторять неизменный некорректный вызов и не запускать auth repair. |
| Явный safety/approval denial | Сохранить полный исходный payload/ответ приватно, публично tool, цель, эффект, хеш и точную доступную причину без секретов. Chief определяет конкретный способ обычного согласования либо существенно более безопасное изменённое действие с доказанным снижением риска. | Нет автоматического retry, эквивалентной переформулировки, другого worker/account/HA для обхода. Одна общая фраза HOLD не является планом. |
| Timeout после возможной мутации | UNKNOWN: прочитать реальное состояние по известному request/job ID. | Не повторять GPU submit, run_now или другую мутацию до установления исхода. |
| Ошибка приложения/теста | Исправить показанную причину в ограниченном scope и проверить результат. | Не подменять application FAIL ремонтом SSH. |

Для одной непрерывной проблемы использовать первый incident SHA и одного ответственного; новые timestamps не создают новые incidents. ACK означает получение, не восстановление. Неизвестную точную причину отказа так и обозначать; не угадывать внутреннюю политику. Продолжать разрешённую независимую работу.

### Короткий вызов SSH и существующий HA fallback

Для SSH явно задавать один известный host, пользователя, ограниченный эффект и timeout. Упрощение вызова помогает проверить его смысл, но не даёт права повторить отклонённый эффект. Проверенный вариант transport:

```bash
ssh -F /dev/null -i /opt/homeassistant/config/id_ed25519 \
  -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=6 \
  -o StrictHostKeyChecking=yes Xavok@192.168.50.27 'true'
```

Если установлен **именно транспортный сбой**, существующий HA SSH допустим для отдельно разрешённого действия. Не создавать новый bridge и не менять credentials/permissions. В текущей установке общий `ha_call_service` для SSH дал `INVALID_ARGUMENT`; рабочим оказался специализированный запуск **уже существующего** `script.temp_pc_ssh_exec`. Сначала прочитать HA best-practices guide и текущую config скрипта: target обязан оставаться PC device `47f1ec020630ea7ca5668621f7f3bcca`, единственное SSH-действие — `ssh.execute_command`. Не подменять конфиг.

```text
ha_config_set_script(
  script_id="temp_pc_ssh_exec", run="start",
  variables={"command":"true", "timeout":10}, wait=false,
  MandatoryBPS=false, BestPracticeKey=<current key from HA guide>)
```

`start` подтверждает лишь приём. Прочитать новый собственный run через `ha_get_automation_traces(automation_id="script.temp_pc_ssh_exec", run_id=<actual>, sections="actions,error")` и проверить SSH result, command, target, success и code. Проверенный health trace `27ed7f47db6a138a2c51ec58bf987635`: 2026-11-01 07:57:25 UTC, `Xavok-PC`, `true`, success=true, code=0. Это подтверждение транспорта, не разрешение отклонённого GPU/QA-действия. При новом refusal остановить затронутое действие; UNKNOWN не повторять.
