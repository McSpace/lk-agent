# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# НАСЛЕДУЕТ ТРЕБОВАНИЯ
См. [Root Requirements](../CLAUDE.md#критические-требования-платформы-не-ломать)

# КРИТИЧЕСКИЕ ТРЕБОВАНИЯ LIVEKIT AGENT (НЕ ЛОМАТЬ!)

## Voice Processing Pipeline
- [ ] STT (Deepgram) для speech recognition НЕ ЛОМАТЬ
- [ ] LLM (OpenAI GPT) для RPG game master responses
- [ ] TTS (Cartesia, ElevenLabs) для voice synthesis
- [ ] VAD (Silero) для voice activity detection
- [ ] Turn Detection multilingual model

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
- `ELEVENLABS_API_KEY` - ElevenLabs TTS (if used)
- `ELEVENLABS_VOICE_ID` - ElevenLabs voice ID

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

*Новые требования будут добавляться сюда при получении от пользователя*

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