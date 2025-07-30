import logging
from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    RunContext,
    cli,
)
from livekit.agents.llm import function_tool
from livekit.plugins import deepgram, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("rpg-agent")
load_dotenv()

class RPGAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""
            Ты ведущий текстовой ролевой игры на русском языке.
            Ты креативный и интересный рассказчик.
            Отвечай кратко, но увлекательно на русском языке.
            Описывай локации, события и реакции мира на действия игрока.
            Задавай игроку вопросы о его действиях.
            Пользователь будет говорить с тобой на русском языке.
            """.strip()
        )

    async def on_enter(self):
        logger.info("🎮 RPG Agent entered the session")
        # Генерируем приветствие
        await self.session.generate_reply(
            instructions="Поприветствуй игрока и начни новое приключение в фантастическом мире"
        )

    @function_tool
    async def roll_dice(self, context: RunContext, sides: int = 20):
        """
        Бросает игральную кость для определения результата действий.
        
        Args:
            sides: Количество граней на кости (по умолчанию 20)
        """
        import random
        result = random.randint(1, sides)
        logger.info(f"🎲 Dice roll: {result} (d{sides})")
        return f"Результат броска d{sides}: {result}"

    @function_tool 
    async def check_inventory(self, context: RunContext):
        """
        Показывает инвентарь игрока.
        """
        logger.info("🎒 Checking player inventory")
        return "В вашем инвентаре: меч, зелье лечения, 50 золотых монет, факел"

def prewarm(proc: JobProcess):
    """Предзагрузка моделей"""
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("🔥 Models prewarmed")

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 RPG Agent starting for room: {ctx.room.name}")
    
    await ctx.connect()
    logger.info(f"🔗 Connected to room: {ctx.room.name}")

    # Создаем агента
    agent = RPGAgent()

    # Создаем сессию с голосовыми компонентами
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=openai.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS(),
        turn_detection=MultilingualModel(),
    )

    # Добавляем обработчики событий
    @session.on("user_speech_committed")
    def on_user_speech_committed(msg):
        logger.info(f"🎤 Player said: {msg.content}")

    @session.on("agent_speech_committed") 
    def on_agent_speech_committed(msg):
        logger.info(f"🗣️ Agent said: {msg.content}")

    @session.on("user_started_speaking") 
    def on_user_started_speaking():
        logger.info("👂 Player started speaking")

    @session.on("user_stopped_speaking")
    def on_user_stopped_speaking():
        logger.info("🤫 Player stopped speaking")

    # Запускаем сессию
    logger.info("🎯 Starting RPG session...")
    await session.start(agent=agent, room=ctx.room)
    logger.info("✅ RPG session started successfully")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm
    ))