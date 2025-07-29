import logging
from livekit.agents import JobContext, WorkerOptions, cli
import livekit.rtc as rtc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("basic-agent")

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 Basic agent starting for room: {ctx.room.name}")
    
    await ctx.connect()
    logger.info(f"🔗 Connected to room: {ctx.room.name}")

    # Ждем пользователя
    logger.info("⏳ Waiting for participant...")
    participant = await ctx.wait_for_participant()
    logger.info(f"✅ Participant joined: {participant.identity}")

    # Отправляем простое сообщение через data channel
    greeting = "Привет! Агент подключен успешно. Если вы это видите в логах - соединение работает!"
    
    await ctx.room.local_participant.publish_data(
        greeting.encode('utf-8'), 
        reliable=True,
        topic="greeting"
    )
    logger.info(f"📨 Sent greeting message: {greeting}")

    # Слушаем сообщения от пользователя
    @ctx.room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        logger.info(f"📨 Received data: {data.data.decode('utf-8')}")
        # Эхо ответ
        echo_msg = f"Получил: {data.data.decode('utf-8')}"
        ctx.room.local_participant.publish_data(
            echo_msg.encode('utf-8'),
            reliable=True,
            topic="echo"
        )

    # Логируем события участников
    @ctx.room.on("participant_connected")
    def on_participant_connected(p):
        logger.info(f"👋 New participant: {p.identity}")

    @ctx.room.on("track_published")
    def on_track_published(publication, participant):
        logger.info(f"🎵 Track published: {publication.sid} by {participant.identity}")

    logger.info("🎯 Agent is running and listening for events...")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))