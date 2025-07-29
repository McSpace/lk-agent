import logging
from livekit.agents import JobContext, WorkerOptions, cli

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test-connection")

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 Testing connection to room: {ctx.room.name}")
    
    try:
        await ctx.connect()
        logger.info(f"✅ Successfully connected to room: {ctx.room.name}")
        logger.info(f"📊 Current participants: {len(ctx.room.remote_participants)}")
        
        # Ждем пользователя
        logger.info("⏳ Waiting for participant to join...")
        participant = await ctx.wait_for_participant()
        logger.info(f"🎉 Participant joined: {participant.identity}")
        
        # Просто держим соединение
        logger.info("✅ Connection test successful! Agent is running...")
        
        # Будем логировать новых участников
        def on_participant_connected(p):
            logger.info(f"👋 New participant: {p.identity}")
            
        ctx.room.on("participant_connected", on_participant_connected)
        
    except Exception as e:
        logger.error(f"❌ Connection failed: {e}")
        raise

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))