import asyncio
from livekit import RoomServiceClient
# from livekit.agents import JobContext #, VoiceAssistant
# from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, openai, silero, elevenlabs
from livekit.agents import create_worker
# import silero
# import deepgram
# import openai
# import elevenlabs

# Настройка клиента RoomService
room_service = RoomServiceClient(
    host="wss://ttsm-bq38y43t.livekit.cloud",
    api_key="API4KF6voZ4TBJ3",
    api_secret="fITLfyG9UPrmeOkB3X4MkItspTqxU74XOeEkb0NM3rZD"
)

# Функция-обработчик агента
async def agent_handler(ctx: JobContext):
    # Настройка компонентов агента
    vad = silero.VAD()
    stt = deepgram.STT()
    llm = openai.LLM()
    tts = elevenlabs.TTS()
    
    assistant = VoiceAssistant(vad, stt, llm, tts, allow_interruptions=True)
    assistant.set_system_message(["Вы - голосовой ассистент, способный общаться с несколькими участниками."])
    
    await assistant.say('Здравствуйте! Я готов общаться всеми участниками.')

    @ctx.room.on("participant_connected")
    def on_participant_connected(participant):
        assistant.start(ctx.room, participant)

    # Основной цикл обработки взаимодействий
    while True:
        # Здесь можно добавить дополнительную логику обработки входящих сообщений
        # и генерации ответов для нескольких участников
        await asyncio.sleep(1)

# Создание и настройка worker'а
worker = create_worker(
    host="wss://ttsm-bq38y43t.livekit.cloud",
    api_key="API4KF6voZ4TBJ3",
    api_secret="fITLfyG9UPrmeOkB3X4MkItspTqxU74XOeEkb0NM3rZD"
)

# Регистрация агента
worker.register_job("multi_participant_agent", agent_handler)

# Создание комнаты
room = room_service.create_room("multi_participant_room")

# Генерация токенов
agent_token = room_service.create_token(
    room_name="quickstart-room1",
    identity="ai_agent",
    name="AI Assistant"
)

# Пример генерации токена для одного участника
# (в реальном приложении вы бы генерировали токены для каждого участника)
participant_token = room_service.create_token(
    room_name="multi_participant_room",
    identity="participant_1",
    name="User 1"
)

# Запуск worker'а
if __name__ == "__multy-agent__":
    worker.run()