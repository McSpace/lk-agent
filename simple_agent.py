import logging
from livekit.agents import (
    Agent,
    AgentSession, 
    JobContext,
    WorkerOptions,
    cli
)
from livekit.plugins import deepgram, openai, silero

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simple-agent")

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 Simple agent starting for room: {ctx.room.name}")
    
    await ctx.connect()
    logger.info(f"🔗 Connected to room: {ctx.room.name}")

    # Создаем агента
    agent = Agent(
        instructions="Ты дружелюбный голосовой ассистент. Отвечай кратко на русском языке."
    )

    # Создаем сессию с компонентами
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(language="ru"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS()
    )

    # Добавляем обработчики событий
    @session.on("user_speech_committed")
    def on_user_speech_committed(msg):
        logger.info(f"🎤 User said: {msg.content}")

    @session.on("agent_speech_committed") 
    def on_agent_speech_committed(msg):
        logger.info(f"🤖 Agent said: {msg.content}")

    # Запускаем сессию
    logger.info("🤖 Starting agent session...")
    await session.start(agent=agent, room=ctx.room)
    logger.info("✅ Agent session started")

    # Простое приветствие без LLM
    import livekit.rtc as rtc
    from livekit.agents import tts
    
    try:
        # Создаем простой текст
        greeting_text = "Привет! Я голосовой ассистент. Скажите что-нибудь!"
        logger.info(f"📢 Sending greeting: {greeting_text}")
        
        # Синтезируем речь
        tts_engine = openai.TTS()
        tts_stream = tts_engine.synthesize(greeting_text)
        
        # Создаем аудио трек
        source = rtc.AudioSource(sample_rate=24000, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("agent-audio", source)
        
        # Публикуем трек
        publication = await ctx.room.local_participant.publish_track(track)
        logger.info("🎵 Audio track published")
        
        # Проигрываем TTS
        async for audio_frame in tts_stream:
            await source.capture_frame(audio_frame.frame)
            
        logger.info("✅ Greeting played successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to play greeting: {e}")
        
        # Fallback - простое текстовое сообщение
        logger.info("📝 Sending text fallback greeting")
        await ctx.room.local_participant.publish_data(
            greeting_text.encode(), 
            reliable=True
        )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint
    ))