# LiveKit Agent for AI Worlds

**Part of the aiworlds.online ecosystem**

## About aiworlds.online Platform

**aiworlds.online** is an experimental platform for testing and applying cutting-edge AI technologies in interactive experiences. The platform focuses on creating immersive voice-driven RPG games that combine multiple AI services into seamless real-time interactions.

### Platform Components

The aiworlds.online ecosystem consists of several interconnected services:

- **lk-agent** (this repository) - LiveKit-based voice agent for real-time RPG game narration
- **story-api** - Backend API for game data, user management, and turn persistence
- **story-front** - Frontend web application for game interface and visualization
- **StoryImageGen** - AI-powered image generation service for scene visualization

## Project Overview

**lk-agent** is a real-time voice agent built on [LiveKit Agents SDK](https://docs.livekit.io/agents/) that powers interactive RPG experiences with AI-driven game master narration. The agent processes player voice input, generates contextual responses using LLM, and delivers natural speech output in multiple languages.

### Key Features

- **Real-time Voice Interaction** - Seamless voice-to-voice communication with sub-second latency
- **Multi-language Support** - Full support for English, Russian, Dutch, French, and Spanish
- **Dynamic Language Switching** - Change language on-the-fly during active sessions
- **AI Game Master** - Context-aware RPG narration powered by GPT-4o
- **Scene Visualization** - Automatic generation of scene images for each turn
- **Persistent Game State** - Integration with backend API for game progression tracking
- **Conversation Summaries** - Automatic summarization every 6 turns for context management

## Architecture

### Voice Processing Pipeline

The agent implements a sophisticated voice processing pipeline:

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Player    │────▶│     VAD      │────▶│     STT      │────▶│     LLM      │
│   Audio     │     │   (Silero)   │     │  (Deepgram)  │     │  (GPT-4o)    │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                                                                       │
                                                                       ▼
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Player    │◀────│     TTS      │◀────│  Turn Detect │◀────│  Response    │
│   Audio     │     │  (Cartesia)  │     │(Multilingual)│     │  Generation  │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

#### Pipeline Components

1. **VAD (Voice Activity Detection)** - Silero VAD detects when player starts/stops speaking
2. **STT (Speech-to-Text)** - Deepgram nova-3 model with multilingual support
3. **LLM (Language Model)** - OpenAI GPT-4o generates contextual RPG responses
4. **Turn Detection** - Multilingual model manages conversation flow
5. **TTS (Text-to-Speech)** - Cartesia sonic-2 synthesizes natural voice output

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        aiworlds.online                          │
│                                                                 │
│  ┌────────────────┐      ┌───────────────┐      ┌──────────┐  │
│  │  story-front   │◀────▶│   lk-agent    │◀────▶│story-api │  │
│  │   (Web UI)     │      │ (Voice Agent) │      │(Backend) │  │
│  └────────────────┘      └───────────────┘      └──────────┘  │
│         │                        │                     │        │
│         │                        │                     │        │
│         │                        ▼                     │        │
│         │              ┌──────────────────┐            │        │
│         └─────────────▶│ StoryImageGen    │◀───────────┘        │
│                        │ (Image AI)       │                     │
│                        └──────────────────┘                     │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │               LiveKit Server (Real-time Media)           │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Game Initialization** - Agent fetches game data from story-api
2. **Voice Input** - Player speaks, audio processed through VAD → STT
3. **Context Building** - Game state + conversation history + player input
4. **Response Generation** - LLM generates RPG narration
5. **Image Generation** - StoryImageGen creates scene visualization (async)
6. **Voice Output** - TTS synthesizes response in selected language
7. **State Persistence** - Turn saved to story-api with image URL

## Technology Stack

### Core Technologies

- **Framework**: [LiveKit Agents SDK 1.x](https://docs.livekit.io/agents/)
- **Language**: Python 3.11+
- **Real-time Media**: LiveKit Cloud/Server

### AI Services Integration

| Component | Provider | Model | Purpose |
|-----------|----------|-------|---------|
| STT | Deepgram | nova-3 | Speech recognition with multilingual support |
| LLM | OpenAI | gpt-4o | RPG game master responses |
| TTS | Cartesia | sonic-2 | Natural voice synthesis (5 languages) |
| VAD | Silero | - | Voice activity detection |
| Image Gen | Custom | Stable Diffusion | Scene visualization |

### Voice Models by Language

The agent uses optimized voice models for each supported language:

| Language | Code | TTS Voice ID | Model |
|----------|------|--------------|-------|
| Russian | `ru` | `da05e96d-ca10-4220-9042-d8acef654fa9` | Cartesia sonic-2 |
| English | `en` | `42b39f37-515f-4eee-8546-73e841679c1d` | Cartesia sonic-2 |
| Dutch | `nl` | `9e8db62d-056f-47f3-b3b6-1b05767f9176` | Cartesia sonic-2 |
| French | `fr` | `5c3c89e5-535f-43ef-b14d-f8ffe148c1f0` | Cartesia sonic-2 |
| Spanish | `es` | `2695b6b5-5543-4be1-96d9-3967fb5e7fec` | Cartesia sonic-2 |

## Installation

### Prerequisites

- Python 3.11 or higher
- LiveKit Cloud account or self-hosted LiveKit server
- API keys for all required services (see Configuration)

### Local Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd lk-agent
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Download required models:
```bash
python main.py download-files
```

5. Configure environment variables (see Configuration section)

6. Start the agent:
```bash
python main.py start
```

### Docker Deployment

Build and run using Docker:

```bash
# Build image
docker build -t lk-agent .

# Run container
docker run --env-file .env lk-agent
```

## Configuration

### Environment Variables

Create a `.env` file in the project root with the following variables:

```bash
# LiveKit Configuration
LIVEKIT_URL=wss://your-livekit-server.com
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret

# Backend API
STORY_API_URL=https://your-story-api.com

# AI Services
DEEPGRAM_API_KEY=your-deepgram-key        # For STT (nova-3)
OPENAI_API_KEY=your-openai-key            # For LLM (GPT-4o)
CARTESIA_API_KEY=your-cartesia-key        # For TTS (sonic-2)
```

### Voice Settings

The agent supports runtime voice settings updates via DataChannel:

```json
{
  "type": "voice_settings_update",
  "language": "en",
  "speech_speed": 1.0
}
```

**Supported Languages**: `en`, `ru`, `nl`, `fr`, `es`

**Supported Speeds**: `0.5`, `0.75`, `1.0`, `1.5`, `1.75`

## Integration Points

### Story API Integration

The agent communicates with story-api for:

- **GET** `/api/v1/games/{game_id}` - Fetch game data and context
- **POST** `/api/v1/turns` - Save player turns and GM responses
- **POST** `/api/v1/summary/{game_id}/generate` - Generate conversation summaries
- **PUT** `/api/v1/users/{user_id}` - Update user language preferences

### StoryImageGen Integration

Scene visualization is generated asynchronously:

- **POST** `https://storyimagegen-production.up.railway.app/process_chat`
  - Generates contextual scene images based on GM response
  - Returns image URL for frontend display
  - Timeout: 60 seconds

### Frontend Integration (DataChannel)

Real-time communication with story-front via LiveKit DataChannel:

**Topics:**
- `topic1` - Image URL delivery to frontend
- `voice_settings_response` - Confirmation of settings updates

## Development

### Project Structure

```
lk-agent/
├── main.py              # Main agent implementation
├── voice_factory.py     # Voice component factory (legacy)
├── requirements.txt     # Python dependencies
├── Dockerfile          # Container configuration
├── CLAUDE.md           # Development guidelines
└── README.md           # This file
```

### Key Classes

- **Assistant** - Main agent class extending LiveKit Agent
- **GameData** - Pydantic model for game state
- **UserVoiceSettings** - Voice configuration model

### Development Commands

```bash
# Start agent locally
python main.py start

# Download models (run before first start)
python main.py download-files

# Run with specific log level
LOG_LEVEL=DEBUG python main.py start
```

## Critical Requirements

### Voice Pipeline Stability

The voice processing pipeline is production-tested and optimized. When making changes:

1. **Always consult LiveKit 1.x documentation** before modifications
2. **Check official examples** before implementing new features
3. **Use only official LiveKit API methods**
4. **Do not create custom solutions** if official API exists

### Migration Resources

- Official documentation: https://docs.livekit.io/agents/
- Python API Reference: https://docs.livekit.io/reference/python/v1/livekit/agents/
- GitHub examples: https://github.com/livekit-examples/python-agents-examples
- Migration guide: https://docs.livekit.io/agents/start/v0-migration/

## Features in Detail

### Multi-language Support

- Automatic language detection from user settings
- Dynamic language switching during active sessions
- Language-specific STT/TTS configuration
- Database persistence of user language preferences

### Game State Management

- Fetches game world and character data on initialization
- Maintains conversation history across session
- Automatic summary generation every 6 turns
- Final summary on session end

### Session Lifecycle

1. **Session Start** - Fetch game data, initialize voice pipeline
2. **Greeting** - Play intro or latest summary
3. **Game Loop** - Process turns, generate images, save state
4. **Session End** - Generate final summary

### Turn Processing

Each player turn follows this flow:

1. User speaks (VAD detects speech)
2. Speech transcribed (Deepgram STT)
3. LLM generates response (GPT-4o with game context)
4. Response synthesized (Cartesia TTS)
5. Image generated async (StoryImageGen)
6. Turn saved to database (story-api)
7. Image sent to frontend (DataChannel)

## Monitoring and Logging

The agent provides comprehensive logging for debugging:

- Voice pipeline events (VAD, STT, TTS states)
- Session lifecycle (connection, participants, tracks)
- Turn processing (user input, LLM response, image generation)
- API communication (requests, responses, errors)
- Language switching (settings updates, component recreation)

Log levels: DEBUG, INFO, WARNING, ERROR

## Performance Considerations

### Latency Optimization

- VAD prewarming on process start
- Async image generation (non-blocking)
- Streaming LLM responses for faster TTS start
- Multilingual STT model (no language switching delay)

### Resource Management

- Turn detection timing: 1.2s min, 8.0s max endpointing delay
- Summary generation every 6 turns (prevents context overflow)
- Session cleanup on disconnect
- Graceful error handling and fallbacks

## Troubleshooting

### Common Issues

**Agent not responding:**
- Check LiveKit connection status
- Verify all API keys are valid
- Ensure room name matches game ID

**Wrong language:**
- Check user settings in database
- Verify DataChannel message format
- Review language validation in logs

**No images generated:**
- Check StoryImageGen service status
- Verify timeout settings (60s)
- Review image generation logs

**Audio quality issues:**
- Check VAD sensitivity settings
- Verify turn detection timing
- Review STT/TTS model configurations

## Contributing

This is part of the aiworlds.online experimental platform. When contributing:

1. Follow existing code style and conventions
2. Update CLAUDE.md with new requirements
3. Test voice pipeline changes thoroughly
4. Document API integration changes
5. Maintain compatibility with LiveKit 1.x

## License

[Add your license information here]

## Contact & Support

For issues related to:
- **lk-agent** - [Repository Issues]
- **aiworlds.online platform** - [Platform Contact]
- **LiveKit** - https://livekit.io/support

---

Built with LiveKit Agents SDK | Part of aiworlds.online ecosystem
