import logging
from livekit.agents import JobContext, WorkerOptions, cli, llm
from livekit.plugins import openai, deepgram, silero
import livekit.rtc as rtc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("game-agent")

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 Game agent starting for room: {ctx.room.name}")
    
    await ctx.connect()
    logger.info(f"🔗 Connected to room: {ctx.room.name}")

    # Ждем пользователя
    logger.info("⏳ Waiting for participant...")
    participant = await ctx.wait_for_participant()
    logger.info(f"✅ Participant joined: {participant.identity}")

    # Инициализируем компоненты
    tts = openai.TTS()
    stt = deepgram.STT(language="ru")
    llm_engine = openai.LLM(model="gpt-4o-mini")
    vad = silero.VAD.load()
    
    logger.info("🎤 Voice components initialized")

    # Создаем аудио source и track для TTS
    audio_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
    audio_track = rtc.LocalAudioTrack.create_audio_track("agent-voice", audio_source)
    await ctx.room.local_participant.publish_track(audio_track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    logger.info("🎵 Audio track published")

    # История чата для контекста
    chat_history = [
        llm.ChatMessage.create(text="Ты ведущий RPG игры. Отвечай кратко и интересно на русском языке.")
    ]

    async def speak(text: str):
        """Произносит текст через TTS"""
        try:
            logger.info(f"🗣️ Speaking: {text[:100]}...")
            async for audio_frame in tts.synthesize(text):
                await audio_source.capture_frame(audio_frame.frame)
            logger.info("✅ Speech completed")
        except Exception as e:
            logger.error(f"❌ TTS error: {e}")

    async def process_user_speech(audio_data):
        """Обрабатывает речь пользователя"""
        try:
            # STT: речь -> текст
            logger.info("🎧 Processing user speech...")
            
            # Здесь нужно будет добавить обработку аудио данных через STT
            # Пока заглушка
            user_text = "Привет!" # Заглушка
            logger.info(f"🎤 User said: {user_text}")
            
            # LLM: генерируем ответ
            chat_history.append(llm.ChatMessage.create(text=user_text))
            
            logger.info("🧠 Generating AI response...")
            response = await llm_engine.chat(chat_history=chat_history)
            ai_response = response.content
            
            chat_history.append(llm.ChatMessage.create(text=ai_response))
            logger.info(f"🤖 AI response: {ai_response}")
            
            # TTS: ответ -> речь
            await speak(ai_response)
            
        except Exception as e:
            logger.error(f"❌ Speech processing error: {e}")

    # Игровое приветствие
    await speak("Добро пожаловать в игру! Я ваш ведущий. Пока что пишите сообщения в чат, скоро добавлю голосовое управление!")

    # Слушаем текстовые сообщения (временно)
    @ctx.room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        message = data.data.decode('utf-8')
        logger.info(f"📨 Received text: {message}")
        
        # Обрабатываем как игровую команду
        import asyncio
        
        async def process_game_command():
            try:
                # Добавляем в историю чата
                chat_history.append(llm.ChatMessage.create(text=message))
                
                # Генерируем ответ от LLM
                logger.info("🧠 Generating game response...")
                response = await llm_engine.chat(chat_history=chat_history)
                ai_response = response.content
                
                chat_history.append(llm.ChatMessage.create(text=ai_response))
                logger.info(f"🎮 Game response: {ai_response}")
                
                # Произносим ответ
                await speak(ai_response)
                
            except Exception as e:
                logger.error(f"❌ Game command error: {e}")
                await speak("Произошла ошибка. Попробуйте еще раз.")
        
        asyncio.create_task(process_game_command())

    logger.info("🎯 Game agent is running...")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))