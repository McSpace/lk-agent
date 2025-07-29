import logging
from livekit.agents import JobContext, WorkerOptions, cli, llm
from livekit.plugins import openai
import livekit.rtc as rtc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-agent")

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 Voice agent starting for room: {ctx.room.name}")
    
    await ctx.connect()
    logger.info(f"🔗 Connected to room: {ctx.room.name}")

    # Ждем пользователя
    logger.info("⏳ Waiting for participant...")
    participant = await ctx.wait_for_participant()
    logger.info(f"✅ Participant joined: {participant.identity}")

    # Инициализируем TTS
    tts = openai.TTS()
    logger.info("🎤 TTS initialized")

    # Создаем аудио source
    audio_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
    audio_track = rtc.LocalAudioTrack.create_audio_track("agent-voice", audio_source)
    
    # Публикуем аудио трек
    await ctx.room.local_participant.publish_track(audio_track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    logger.info("🎵 Audio track published")

    async def speak(text: str):
        """Произносит текст через TTS"""
        try:
            logger.info(f"🗣️ Speaking: {text[:50]}...")
            
            # Синтезируем речь
            async for audio_frame in tts.synthesize(text):
                await audio_source.capture_frame(audio_frame.frame)
                
            logger.info("✅ Speech completed")
            
        except Exception as e:
            logger.error(f"❌ TTS error: {e}")

    # Приветствие
    await speak("Привет! Я голосовой агент. Пишите сообщения в чат, и я буду их произносить вслух!")

    # Слушаем текстовые сообщения
    @ctx.room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        message = data.data.decode('utf-8')
        logger.info(f"📨 Received: {message}")
        
        # Произносим полученное сообщение
        import asyncio
        asyncio.create_task(speak(f"Вы написали: {message}"))

    logger.info("🎯 Voice agent is running...")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))