# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# INHERITS REQUIREMENTS
See [Root Requirements](../CLAUDE.md#critical-platform-requirements-do-not-break)

# CRITICAL LIVEKIT AGENT REQUIREMENTS (DO NOT BREAK!)

## Voice Processing Pipeline
- [ ] STT (Deepgram nova-3) for speech recognition DO NOT BREAK
- [ ] LLM (OpenAI GPT gpt-4o) for RPG game master responses
- [ ] TTS (Cartesia sonic-2) for voice synthesis DO NOT BREAK
- [ ] VAD (Silero) for voice activity detection
- [ ] Turn Detection multilingual model

## MANDATORY DEVELOPMENT REQUIREMENTS
- [ ] **ALWAYS consult LiveKit 1.x documentation before making code changes**
- [ ] **MUST check LiveKit 1.x examples before implementing new functionality**
- [ ] **USE ONLY official LiveKit 1.x API methods**
- [ ] **DO NOT invent custom solutions if official API exists**

### Resources for verification:
- Official documentation: https://docs.livekit.io/agents/
- Python API Reference: https://docs.livekit.io/reference/python/v1/livekit/agents/
- GitHub examples: https://github.com/livekit-examples/python-agents-examples
- Migration from v0.x: https://docs.livekit.io/agents/start/v0-migration/

## API Integration Points
- [ ] GET /api/v1/games/{game_id} from story-api DO NOT BREAK
- [ ] POST /api/v1/turns to story-api for saving turns
- [ ] StoryImageGen integration for scene visuals
- [ ] LiveKit room management and participant handling

## Multi-language Support
- [ ] Language detection from user settings
- [ ] Russian, English, Dutch, German and Spanish language support
- [ ] Language-specific STT/TTS configuration
- [ ] Localized voice selection

## Game Context Management
- [ ] Game data fetching and processing
- [ ] Conversation history accumulation
- [ ] Session callbacks for lifecycle management
- [ ] JobContext for user data persistence

## REQUIREMENTS MANAGEMENT PROCESS

### When receiving new requirement from user:
1. 🔴 MANDATORY: Document requirement essence in this CLAUDE.md
2. Add to "NEW REQUIREMENTS" section with date
3. Specify priority and cross-service dependencies
4. After implementation, move to "ACTIVE REQUIREMENTS"

### New requirements template:
```
### [DATE] New requirement: [BRIEF DESCRIPTION]
**Description**: [detailed description]
**Priority**: [high/medium/low]
**Affects services**: [list of services]
**Voice pipeline changes**: [yes/no, description]
**API integrations**: [new/changed integrations]
**Status**: [new/in progress/implemented]
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
- `CARTESIA_API_KEY` - Cartesia TTS API key for sonic-2 model

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

# NEW REQUIREMENTS

### [2025-11-12] Add download-files command for Docker build
**Description**: Implemented missing download-files command that Dockerfile uses to preload models at build time.
**Priority**: critical
**Affects services**: lk-agent
**Voice pipeline changes**: no, infrastructure fix only
**API integrations**: no changes
**Status**: implemented

**Problem**:
- Dockerfile line 45 calls `RUN python main.py download-files`
- This command was not implemented in main.py
- Docker build failed because models weren't preloaded
- Production containers need models cached at build time

**Solution**:
- ✅ Added sys.argv parsing for "download-files" command
- ✅ Download Silero VAD models via `silero.VAD.load()`
- ✅ Download turn detector models via `Plugin.registered_plugins()`
- ✅ Exit with code 0 after successful download
- ✅ All models now cached in Docker image during build

**Technical details**:
```python
if len(sys.argv) > 1 and sys.argv[1] == "download-files":
    # Download Silero VAD models
    silero.VAD.load()

    # Download multilingual turn detector models
    from livekit.plugins.turn_detector import Plugin
    plugins = Plugin.registered_plugins()
    for plugin in plugins:
        if hasattr(plugin, 'download_files'):
            plugin.download_files()

    sys.exit(0)
```

**Models downloaded**:
- Silero VAD models (voice activity detection)
- Multilingual turn detector models (en, multilingual)
- AutoTokenizer and model_q8.onnx files
- languages.json configuration

### [2025-11-12] Fix AgentSession initialization syntax error
**Description**: Fixed syntax error in main.py line 936 where commented TTS code block caused ambiguous parameter separation in AgentSession constructor.
**Priority**: critical
**Affects services**: lk-agent
**Voice pipeline changes**: no, code formatting fix only
**API integrations**: no changes
**Status**: implemented

**Problem**:
- Initial Docker build showed `SyntaxError: invalid syntax. Perhaps you forgot a comma?` at line 627 (now 936)
- Commented `elevenlabs.TTS()` block left ambiguous blank line before `vad` parameter
- Python parser couldn't determine if commented section was part of function call

**Solution**:
- ✅ Removed blank line between commented TTS block and `vad` parameter
- ✅ Ensured proper Python function call syntax
- ✅ Fixed syntax but revealed missing download-files command

**Technical details**:
```python
# Before (syntax error):
tts=create_cartesia_tts(...),
# tts=elevenlabs.TTS(...),

vad=ctx.proc.userdata["vad"],

# After (fixed):
tts=create_cartesia_tts(...),
# tts=elevenlabs.TTS(...),
vad=ctx.proc.userdata["vad"],
```

### [2025-08-29] Migration to Cartesia TTS for all languages
**Description**: Replaced mixed OpenAI/Cartesia TTS architecture with unified Cartesia sonic-2 for all supported languages. Removed complex fallback logic.
**Priority**: high
**Affects services**: lk-agent
**Voice pipeline changes**: yes, full TTS provider replacement with Cartesia
**API integrations**: replaced OpenAI TTS API with Cartesia TTS API
**Status**: implemented

**Implemented changes**:
- ✅ Created create_cartesia_tts() function with voice mapping for 5 languages
- ✅ Removed create_tts_with_fallback() with fallback logic
- ✅ Updated AgentSession initialization to use Cartesia
- ✅ Updated recreate_tts_component() for Cartesia
- ✅ Updated documentation with CARTESIA_API_KEY requirement

**Supported voices**:
- Russian (ru): `da05e96d-ca10-4220-9042-d8acef654fa9`
- English (en): `42b39f37-515f-4eee-8546-73e841679c1d`
- Dutch (nl): `9e8db62d-056f-47f3-b3b6-1b05767f9176`
- French (fr): `5c3c89e5-535f-43ef-b14d-f8ffe148c1f0`
- Spanish (es): `2695b6b5-5543-4be1-96d9-3967fb5e7fec`

### [2025-08-29] Deepgram STT setup with nova-3 model
**Description**: Replaced OpenAI STT with Deepgram STT using nova-3 model for improved speech recognition. Added support for dynamic language and runtime STT component recreation.
**Priority**: high
**Affects services**: lk-agent
**Voice pipeline changes**: yes, STT provider replacement from OpenAI to Deepgram
**API integrations**: added Deepgram API integration
**Status**: implemented

**Implemented changes**:
- ✅ Created create_stt_for_language() with multilingual support
- ✅ Updated AgentSession initialization with Deepgram STT (nova-3)
- ✅ Added recreate_stt_component() method for dynamic language update
- ✅ Integrated STT recreation on language change in update_voice_settings()
- ✅ Updated documentation with DEEPGRAM_API_KEY requirement

**Multilingual Support**:
- Nova-3 uses `language=multi` for automatic language detection
- Supports switching between languages in single audio stream
- Supported languages: English, Spanish, French, German, Hindi, Russian, Portuguese, Japanese, Italian, Dutch

### [2025-08-14] Save new language to database
**Description**: Added integration with new API to save language changes to user.language_code. Now on language change, agent not only changes runtime settings but also updates database.
**Priority**: high
**Affects services**: lk-agent, story-api integration
**Voice pipeline changes**: no changes to existing components
**API integrations**: added PUT /api/v1/users/{user_id} call to update user language
**Status**: implemented

**Implemented changes**:
- ✅ Added user update API call in DataChannel handler
- ✅ Logging of successful/failed language update in DB
- ✅ API call error handling with detailed logging
- ✅ Language change check before API call

### [2025-08-08] Fix real-time language switching issue
**Description**: Agent receives language change signal from frontend but continues responding in old language. LLM instructions and TTS components don't update at runtime.
**Priority**: high
**Affects services**: lk-agent, integration with story-front via DataChannel
**Voice pipeline changes**: yes, requires runtime TTS component recreation
**API integrations**: improved DataChannel message handling from frontend
**Status**: implemented

**FIX**: Found issue with `update_instructions()` - it doesn't affect existing chat context

**New solution**: Combined approach with `update_instructions()` + `update_chat_ctx()` to modify existing chat history with new system instructions in correct language

**Issues (fixed)**:
- ✅ LLM instructions now update via update_llm_instructions()
- ✅ TTS component recreates via recreate_tts_component() and tts_node()
- ✅ User settings have priority over game_data.user_lang
- ✅ Improved DataChannel message logging with detailed diagnostics

**Implemented changes**:
- ✅ update_llm_instructions() method for runtime instruction updates
- ✅ recreate_tts_component() method for TTS component recreation
- ✅ Overridden tts_node() for dynamic TTS usage
- ✅ Fixed language settings priority in entrypoint()
- ✅ Improved DataChannel handling with async/await pattern
- ✅ Added language save to database via API

# REQUIREMENTS HISTORY

## [2025-08-07] Requirements management system for LiveKit Agent
**Description**: Update lk-agent/CLAUDE.md with critical voice processing pipeline requirements
**Priority**: high
**Affects services**: lk-agent, story-api integration, StoryImageGen
**Voice pipeline changes**: no changes to existing components
**API integrations**: preserve existing story-api and StoryImageGen integrations
**Status**: implemented

**Requirements**:
- Voice processing pipeline DO NOT BREAK
- API integrations with story-api preserved
- Multi-language support (ru, en, nl, es, ge)
- LiveKit room management
