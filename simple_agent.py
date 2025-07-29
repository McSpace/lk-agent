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

    # Отправляем приветствие
    await session.generate_reply(
        instructions="Поприветствуй пользователя и скажи что ты готов к разговору"
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint
    ))