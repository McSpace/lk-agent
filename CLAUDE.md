# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# НАСЛЕДУЕТ ТРЕБОВАНИЯ
См. [Root Requirements](../CLAUDE.md#критические-требования-платформы-не-ломать)

# КРИТИЧЕСКИЕ ТРЕБОВАНИЯ LIVEKIT AGENT (НЕ ЛОМАТЬ!)

## Voice Processing Pipeline
- [ ] STT (Deepgram nova-3) для speech recognition НЕ ЛОМАТЬ
- [ ] LLM (OpenAI GPT gpt-4o) для RPG game master responses
- [ ] TTS (Cartesia sonic-3.5) для voice synthesis НЕ ЛОМАТЬ
- [ ] VAD (Silero) для voice activity detection
- [ ] Turn Detection multilingual model

## ОБЯЗАТЕЛЬНОЕ ТРЕБОВАНИЕ ДЛЯ РАЗРАБОТКИ
- [ ] **ВСЕГДА сверяться с документацией LiveKit 1.x перед изменениями кода**
- [ ] **ОБЯЗАТЕЛЬНО проверять примеры на LiveKit 1.x перед реализацией новой функциональности**
- [ ] **ИСПОЛЬЗОВАТЬ ТОЛЬКО официальные API методы LiveKit 1.x**
- [ ] **НЕ изобретать самодельные решения если есть официальный API**

### Ресурсы для проверки:
- Официальная документация: https://docs.livekit.io/agents/
- Python API Reference: https://docs.livekit.io/reference/python/v1/livekit/agents/
- GitHub примеры: https://github.com/livekit-examples/python-agents-examples
- Миграция с v0.x: https://docs.livekit.io/agents/start/v0-migration/

## API Integration Points
- [ ] GET /api/v1/games/{game_id} от story-api НЕ ЛОМАТЬ
- [ ] POST /api/v1/turns к story-api для saving turns
- [ ] StoryImageGen integration для scene visuals
- [ ] LiveKit room management и participant handling

## Multi-language Support
- [ ] Language detection from user settings
- [ ] Russian, English, Dutch, German and Spanish language support
- [ ] Language-specific STT/TTS configuration
- [ ] Localized voice selection

## Game Context Management
- [ ] Game data fetching и processing
- [ ] Conversation history accumulation
- [ ] Session callbacks для lifecycle management
- [ ] JobContext for user data persistence

## ПРОЦЕСС УПРАВЛЕНИЯ ТРЕБОВАНИЯМИ

### При получении нового требования от пользователя:
1. 🔴 ОБЯЗАТЕЛЬНО зафиксировать суть требования в этом CLAUDE.md
2. Добавить в секцию "НОВЫЕ ТРЕБОВАНИЯ" с датой
3. Указать приоритет и межсервисные зависимости
4. После реализации переместить в "АКТИВНЫЕ ТРЕБОВАНИЯ"

### Шаблон новых требований:
```
### [ДАТА] Новое требование: [КРАТКОЕ ОПИСАНИЕ]
**Описание**: [детальное описание]
**Приоритет**: [высокий/средний/низкий] 
**Влияет на сервисы**: [список сервисов]
**Voice pipeline changes**: [да/нет, описание]
**API integrations**: [новые/измененные integrations]
**Статус**: [новое/в работе/реализовано]
```

## Project Overview

This is a LiveKit agents collection for real-time voice and audio processing applications. The project contains multiple Python agents that provide different functionalities including RPG game narration, corporate assistance, and speech-to-text transcription.

## Development Commands

- `python main.py start` - Start the main RPG game agent
- `python main.py download-files` - Download required model files (used in Docker build)
- `pip install -r requirements.txt` - Install dependencies

## Key Architecture

### Tech Stack
- **Framework**: LiveKit Agents SDK 1.x
- **Language**: Python 3.11+
- **STT**: Deepgram
- **TTS**: Cartesia, ElevenLabs
- **LLM**: OpenAI (o4-mini)
- **VAD**: Silero
- **Turn Detection**: Multilingual Model
- **HTTP Client**: aiohttp
- **Environment**: python-dotenv

### Agent Types

#### 1. Main RPG Agent (`main.py`)
- **Purpose**: AI-powered RPG game master for interactive storytelling
- **Features**: 
  - Fetches game data from Story API
  - Multi-language support (English, Russian, Dutch)
  - Language-specific TTS voice selection
  - Game state management with Pydantic models
- **API Integration**: Connects to `STORY_API_URL` for game data retrieval
- **Key Classes**: `GameData`, `Game`, `GameSummary`, `Assistant`


### Core LiveKit Integration

#### Agent Session Management
```python
session = AgentSession(
    stt=deepgram.STT(language=user_lang_code),
    llm=openai.LLM(model="o4-mini"),
    tts=cartesia.TTS(speed=0.5, voice="voice-id"),
    vad=silero.VAD.load(),
    turn_detection=MultilingualModel(),
)
```

#### Pipeline Components
- **VAD (Voice Activity Detection)**: Silero for detecting speech
- **STT (Speech-to-Text)**: Deepgram with language-specific models
- **LLM (Large Language Model)**: OpenAI GPT models for conversation
- **TTS (Text-to-Speech)**: Cartesia for voice synthesis
- **Turn Detection**: Multilingual support for conversation flow

### Environment Configuration

Required environment variables:
- `LIVEKIT_API_KEY` - LiveKit API authentication
- `LIVEKIT_API_SECRET` - LiveKit API secret
- `LIVEKIT_URL` - LiveKit server URL
- `STORY_API_URL` - Backend API for game data
- `DEEPGRAM_API_KEY` - Deepgram STT API key for nova-3 model
- `OPENAI_API_KEY` - OpenAI API key for LLM only
- `CARTESIA_API_KEY` - Cartesia TTS API key for sonic-3.5 model

### Docker Support

The project includes Docker containerization:
- Uses Python 3.11 slim base image
- Non-privileged user setup for security
- Build-time model downloading
- Production-ready entrypoint configuration

### Key Features

#### Multi-language Support
- Language detection from game data
- Language-specific STT/TTS configuration
- Localized voice selection (Russian, Dutch, English)

#### Real-time Communication
- LiveKit room-based communication
- Audio stream processing
- Data channel messaging
- Participant management

#### State Management
- User data persistence in JobContext
- Session callbacks for lifecycle management
- Chat history accumulation

### Development Notes

- Uses asyncio for concurrent operations
- Comprehensive logging with different log levels
- Error handling for API communication
- Pydantic models for data validation
- Virtual environment included (`venv/` directory)

# НОВЫЕ ТРЕБОВАНИЯ

### [2026-05-22] Cartesia TTS: переход sonic-2 → sonic-3.5
**Описание**: Cartesia деприкейтит часть моделей с 2026-06-01. Меняем `model="sonic-2"` → `model="sonic-3.5"` во всех точках создания Cartesia TTS (`main.py:create_cartesia_tts`, `voice_factory.py` для всех языков). Voice ID'ы тех же 5 голосов сохраняются — Cartesia поддерживает их в новой модели.
**Приоритет**: высокий (deadline 2026-06-01)
**Влияет на сервисы**: lk-agent
**Voice pipeline changes**: да, смена TTS-модели; STT/VAD/LLM не затронуты
**API integrations**: тот же Cartesia API, изменена только строка модели
**Backwards compatibility**: voice_id'ы сохраняются; в случае регресса по тембру/качеству — rollback одной правкой обратно на sonic-2 до 2026-06-01
**Статус**: реализовано

**Реализованные изменения**:
- ✅ `lk-agent/main.py` — `create_cartesia_tts()` использует `model="sonic-3.5"`
- ✅ `lk-agent/voice_factory.py` — все три фабрики TTS используют `model="sonic-3.5"`
- ✅ Документация обновлена: lk-agent/CLAUDE.md, корневой CLAUDE.md (env-описание и TTS Pipeline)

**Operator steps на test env**:
1. После деплоя — открыть игру на каждом из 5 языков (ru, en, nl, fr, es), послушать первую реплику ведущего на предмет регрессии по тембру/латентности
2. В случае проблем — откат: `sed -i '' 's/sonic-3.5/sonic-2/g' main.py voice_factory.py` + новый коммит до 2026-06-01

### [2026-05-19] player_state + tool calling (инвентарь/внешний вид/статусы + skill checks)
**Описание**: Ведущему включён полноценный tool calling. Появилось три function_tool: `update_player_state(new_state, reason)` — переписывает целиком freeform-текст состояния игрока (инвентарь, внешний вид, статусы) и сохраняет в `games.player_state` через `PATCH /api/v1/games/{game_id}/player-state`; `skill_check(description, difficulty)` — d20 vs DC (easy=8/medium=12/hard=16/very_hard=20) с outcome critical_success/success/failure/critical_failure; `roll_dice(sides=20)` — простой бросок. Каждый вызов tool'а публикуется в data channel под топиком `agent_event` (`{type, tool, payload, ts}`) — фронт логирует в console.log для дебага.
**Приоритет**: высокий
**Влияет на сервисы**: lk-agent (новые tools, обновлённый промпт), story-api (новая колонка `games.player_state` + PATCH-эндпоинт), story-front (console-логгер agent_event)
**Voice pipeline changes**: нет
**API integrations**: новый `PATCH /api/v1/games/{game_id}/player-state`; ответ `GET /api/v1/games/{game_id}` теперь включает `player_state: str`
**Backwards compatibility**: поле `player_state` имеет `DEFAULT ''`; старые игры открываются как пустое состояние
**Статус**: реализовано

**Реализованные изменения**:
- ✅ `GameData.player_state: str = ""`
- ✅ HTTP-хелпер `patch_player_state(game_id, new_state)` (aiohttp PATCH)
- ✅ `Assistant._build_instructions()` собирает промпт с актуальным `player_state`; жёсткий запрет упоминания tools/механики/инвентаря/кубиков в нарративе
- ✅ `Assistant.update_llm_instructions()` пересобирает промпт после каждого `update_player_state`
- ✅ Три `@function_tool`: `update_player_state`, `skill_check`, `roll_dice`
- ✅ Хелпер `_publish_tool_event(tool, payload)` пушит JSON в data channel под топиком `agent_event`
- ✅ Удалены закомментированные заглушки `roll_dice`/`check_inventory`/`save_game_state`

**Operator steps на test env**:
1. Применить миграцию story-api: `story-api/migrations/add_player_state_to_games.sql` (пользователь руками в Supabase SQL editor)
2. Деплой story-api → story-front → lk-agent (в lk-agent — push в stage И main, см. соответствующее правило)

### [2026-05-18] Character reference picture → fal.ai edit mode
**Описание**: `GameData` теперь содержит `character_reference_image_url` из `GET /api/v1/games/{game_id}` (новое поле в story-api). `send_to_imageGen_api()` при наличии URL переключает StoryImageGen на `provider="fal_ai"` + `model="fal-ai/flux-2/klein/9b/edit"` + `image_urls=[ref_url]`. Без URL поведение прежнее (дефолты StoryImageGen: `together_ai` + `FLUX.2-flex`).
**Приоритет**: высокий
**Влияет на сервисы**: lk-agent (consumer), story-api (producer), StoryImageGen (downstream)
**Voice pipeline changes**: нет
**API integrations**: обогащённый POST в StoryImageGen `/process_chat` (provider/model/image_urls), story-api `GET /games/{id}` отдаёт `character_reference_image_url`
**Backwards compatibility**: при `reference_image_url IS NULL` цепочка работает как прежде
**Статус**: реализовано

**Реализованные изменения**:
- ✅ `GameData.character_reference_image_url: Optional[str] = None`
- ✅ Условное обогащение payload в `send_to_imageGen_api()` (fal_ai/model/image_urls) + лог режима
- ✅ Rollback panic-button: `UPDATE characters SET reference_image_url = NULL` мгновенно возвращает дефолтный путь без передеплоя

### [2025-08-29] Переход на Cartesia TTS для всех языков
**Описание**: Заменена смешанная OpenAI/Cartesia TTS архитектура на единообразную Cartesia sonic-2 для всех поддерживаемых языков. Убрана сложная fallback логика.
**Приоритет**: высокий
**Влияет на сервисы**: lk-agent
**Voice pipeline changes**: да, полная замена TTS провайдера на Cartesia
**API integrations**: замена OpenAI TTS API на Cartesia TTS API
**Статус**: реализовано

**Реализованные изменения**:
- ✅ Создана функция create_cartesia_tts() с маппингом голосов для 5 языков
- ✅ Удалена функция create_tts_with_fallback() с fallback логикой
- ✅ Обновлена инициализация AgentSession для использования Cartesia
- ✅ Обновлен recreate_tts_component() для Cartesia
- ✅ Обновлена документация с требованием CARTESIA_API_KEY

**Поддерживаемые голоса**:
- Russian (ru): `da05e96d-ca10-4220-9042-d8acef654fa9`
- English (en): `42b39f37-515f-4eee-8546-73e841679c1d`
- Dutch (nl): `9e8db62d-056f-47f3-b3b6-1b05767f9176`
- French (fr): `5c3c89e5-535f-43ef-b14d-f8ffe148c1f0`
- Spanish (es): `2695b6b5-5543-4be1-96d9-3967fb5e7fec`

### [2025-08-29] Настройка Deepgram STT с моделью nova-3
**Описание**: Заменен OpenAI STT на Deepgram STT с моделью nova-3 для улучшенного распознавания речи. Добавлена поддержка динамического языка и пересоздания STT компонента в runtime.
**Приоритет**: высокий
**Влияет на сервисы**: lk-agent
**Voice pipeline changes**: да, замена STT провайдера с OpenAI на Deepgram
**API integrations**: добавлена интеграция с Deepgram API
**Статус**: реализовано

**Реализованные изменения**:
- ✅ Создана функция create_stt_for_language() с поддержкой многоязычности
- ✅ Обновлена инициализация AgentSession с Deepgram STT (nova-3)
- ✅ Добавлен метод recreate_stt_component() для динамического обновления языка
- ✅ Интегрировано пересоздание STT при смене языка в update_voice_settings()
- ✅ Обновлена документация с требованием DEEPGRAM_API_KEY

**Multilingual Support**:
- Nova-3 использует `language=multi` для автоматического определения языка
- Поддерживает переключение между языками в одном аудиопотоке
- Поддерживаемые языки: English, Spanish, French, German, Hindi, Russian, Portuguese, Japanese, Italian, Dutch

### [2025-08-14] Сохранение нового языка в базу данных
**Описание**: Добавлена интеграция с новым API для сохранения изменений языка в user.language_code. Теперь при смене языка агент не только меняет runtime настройки, но и обновляет базу данных.
**Приоритет**: высокий
**Влияет на сервисы**: lk-agent, story-api integration
**Voice pipeline changes**: нет изменений в существующих компонентах
**API integrations**: добавлен вызов PUT /api/v1/users/{user_id} для обновления языка пользователя
**Статус**: реализовано

**Реализованные изменения**:
- ✅ Добавлен вызов API обновления пользователя в DataChannel обработчике
- ✅ Логирование успешного/неуспешного обновления языка в БД
- ✅ Обработка ошибок API вызовов с детальным логированием
- ✅ Проверка изменения языка перед вызовом API

### [2025-08-08] Исправление проблемы смены языка в реальном времени
**Описание**: Агент получает сигнал смены языка от фронтенда, но продолжает отвечать на старом языке. LLM инструкции и TTS компоненты не обновляются в runtime.
**Приоритет**: высокий
**Влияет на сервисы**: lk-agent, интеграция с story-front через DataChannel
**Voice pipeline changes**: да, требуется пересоздание TTS компонента в runtime
**API integrations**: улучшение обработки DataChannel сообщений от фронтенда
**Статус**: реализовано

**ИСПРАВЛЕНИЕ**: Найдена проблема с `update_instructions()` - он не влияет на существующий chat context

**Новое решение**: Комбинированный подход с `update_instructions()` + `update_chat_ctx()` для модификации существующей истории чата с новыми системными инструкциями на правильном языке

**Проблемы (исправлены)**:
- ✅ LLM инструкции теперь обновляются через update_llm_instructions()
- ✅ TTS компонент пересоздается через recreate_tts_component() и tts_node()
- ✅ User settings имеют приоритет над game_data.user_lang
- ✅ Улучшено логирование DataChannel сообщений с детальной диагностикой

**Реализованные изменения**:
- ✅ Метод update_llm_instructions() для обновления инструкций в runtime
- ✅ Метод recreate_tts_component() для пересоздания TTS компонента
- ✅ Переопределен tts_node() для использования динамического TTS
- ✅ Исправлен приоритет языковых настроек в entrypoint()
- ✅ Улучшена обработка DataChannel с async/await паттерном
- ✅ Добавлено сохранение языка в базу данных через API

# ИСТОРИЯ ТРЕБОВАНИЙ

## [2025-08-07] Система управления требованиями для LiveKit Agent
**Описание**: Обновление lk-agent/CLAUDE.md с критическими требованиями voice processing pipeline
**Приоритет**: высокий
**Влияет на сервисы**: lk-agent, story-api интеграция, StoryImageGen
**Voice pipeline changes**: нет изменений в существующих компонентах
**API integrations**: сохранение существующих story-api и StoryImageGen integrations
**Статус**: реализовано

**Требования**:
- Voice processing pipeline НЕ ЛОМАТЬ
- API integrations с story-api сохраняются
- Multi-language support (ru, en, nl, es, ge)
- LiveKit room management