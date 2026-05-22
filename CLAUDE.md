# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# INHERITS REQUIREMENTS
See [Root Requirements](../CLAUDE.md#critical-platform-requirements-do-not-break)

# CRITICAL LIVEKIT AGENT REQUIREMENTS (DO NOT BREAK!)

## Voice Processing Pipeline
- [ ] STT (Deepgram nova-3) for speech recognition DO NOT BREAK
- [ ] LLM (OpenAI GPT gpt-4o) for RPG game master responses
- [ ] TTS (Cartesia sonic-3.5) for voice synthesis DO NOT BREAK
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

# NEW REQUIREMENTS

### [2026-05-22] Cartesia TTS: sonic-2 → sonic-3.5 migration
**Description**: Cartesia is deprecating sonic-2 on 2026-06-01. Bumps `model="sonic-2"` → `model="sonic-3.5"` at all Cartesia TTS creation sites (`main.py:create_cartesia_tts`, `voice_factory.py` for every language). The 5 voice IDs are preserved — Cartesia supports them on the new model.
**Priority**: high (deadline 2026-06-01)
**Affects services**: lk-agent
**Voice pipeline changes**: yes, TTS model switch; STT/VAD/LLM untouched
**API integrations**: same Cartesia API, only the model string changed
**Backwards compatibility**: voice IDs preserved; if tone/quality regresses, revert with a single edit back to sonic-2 before 2026-06-01
**Status**: implemented

**Implemented changes**:
- ✅ `lk-agent/main.py` — `create_cartesia_tts()` uses `model="sonic-3.5"`
- ✅ `lk-agent/voice_factory.py` — all three TTS factories use `model="sonic-3.5"`
- ✅ Docs updated: lk-agent/CLAUDE.md, root CLAUDE.md (env description and TTS Pipeline)

**Operator steps on test env**:
1. After deploy, open a game in each of the 5 languages (ru, en, nl, fr, es) and listen to the first GM line for regressions in tone/latency
2. If anything breaks, roll back: `sed -i '' 's/sonic-3.5/sonic-2/g' main.py voice_factory.py` + new commit before 2026-06-01

### [2026-05-19] player_state + tool calling (inventory/appearance/statuses + skill checks)
**Description**: Full tool calling enabled for the GM. Three function_tools landed: `update_player_state(new_state, reason)` overwrites the freeform player_state text (inventory, appearance, statuses) and persists it via `PATCH /api/v1/games/{game_id}/player-state`; `skill_check(description, difficulty)` rolls d20 vs DC (easy=8/medium=12/hard=16/very_hard=20) with outcome critical_success/success/failure/critical_failure; `roll_dice(sides=20)` is a plain die roll. Every tool invocation is also published to the data channel under topic `agent_event` (`{type, tool, payload, ts}`) for frontend console-logging.
**Priority**: high
**Affects services**: lk-agent (new tools, rewritten prompt), story-api (new `games.player_state` column + PATCH endpoint), story-front (agent_event console-logger)
**Voice pipeline changes**: no
**API integrations**: new `PATCH /api/v1/games/{game_id}/player-state`; `GET /api/v1/games/{game_id}` response now includes `player_state: str`
**Backwards compatibility**: `player_state` has `DEFAULT ''` — existing games open with empty state
**Status**: implemented

**Implemented changes**:
- ✅ `GameData.player_state: str = ""`
- ✅ HTTP helper `patch_player_state(game_id, new_state)` (aiohttp PATCH)
- ✅ `Assistant._build_instructions()` builds the prompt with the live `player_state`; hard ban on mentioning tools/mechanics/inventory/dice in narration
- ✅ `Assistant.update_llm_instructions()` rebuilds the prompt after every `update_player_state`
- ✅ Three `@function_tool`s: `update_player_state`, `skill_check`, `roll_dice`
- ✅ `_publish_tool_event(tool, payload)` helper pushes JSON to the data channel under topic `agent_event`
- ✅ Removed the commented-out stubs `roll_dice`/`check_inventory`/`save_game_state`

**Operator steps on test env**:
1. Apply story-api migration: `story-api/migrations/add_player_state_to_games.sql` (run manually in Supabase SQL editor)
2. Deploy story-api → story-front → lk-agent (lk-agent — push to both `stage` and `master` deploy branches)

### [2026-05-18] Character reference picture → fal.ai edit mode
**Description**: `GameData` now carries `character_reference_image_url` from `GET /api/v1/games/{game_id}` (new field in story-api). `send_to_imageGen_api()` switches StoryImageGen to `provider="fal_ai"` + `model="fal-ai/flux-2/klein/9b/edit"` + `image_urls=[ref_url]` when the URL is present. When absent, behavior is unchanged (StoryImageGen defaults: `together_ai` + `FLUX.2-flex`).
**Priority**: high
**Affects services**: lk-agent (consumer), story-api (producer), StoryImageGen (downstream)
**Voice pipeline changes**: no
**API integrations**: enriched POST to StoryImageGen `/process_chat` (provider/model/image_urls); story-api `GET /games/{id}` returns `character_reference_image_url`
**Backwards compatibility**: when `reference_image_url IS NULL`, chain works as before
**Status**: implemented

**Implemented changes**:
- ✅ `GameData.character_reference_image_url: Optional[str] = None`
- ✅ Conditional payload enrichment in `send_to_imageGen_api()` (fal_ai/model/image_urls) + mode logging
- ✅ Rollback panic-button: `UPDATE characters SET reference_image_url = NULL` instantly reverts to default path without redeploy

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
