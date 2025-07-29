import asyncio
import logging
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, openai, silero

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simple-agent")

def prewarm(proc):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 Simple agent starting for room: {ctx.room.name}")
    
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info(f"🔗 Connected to room: {ctx.room.name}")

    # Простой голосовой ассистент
    assistant = VoiceAssistant(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(language="ru"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS(),
    )

    # Ждем пользователя
    logger.info("⏳ Waiting for participant...")
    participant = await ctx.wait_for_participant()
    logger.info(f"✅ Participant joined: {participant.identity}")

    # Запускаем ассистента
    assistant.start(ctx.room)
    logger.info("🤖 Assistant started")

    # Приветствие
    await assistant.say("Привет! Я простой голосовой ассистент. Скажите что-нибудь!")

    @assistant.on("user_speech_committed")
    def on_user_speech(msg):
        logger.info(f"🎤 User said: {msg.content}")

    @assistant.on("agent_speech_committed")
    def on_agent_speech(msg):
        logger.info(f"🤖 Agent said: {msg.content}")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm
    ))