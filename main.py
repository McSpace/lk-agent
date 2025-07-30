import asyncio
from typing import AsyncIterable
from aiofile import async_open as open
from datetime import datetime
import aiohttp
import os
import dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    RunContext,
    cli,
    llm,
    tts,
    vad,
)
from livekit.agents.llm import function_tool
from livekit.plugins import deepgram, openai, silero, cartesia, google
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from dotenv import load_dotenv
import livekit.api

import logging
from uuid import UUID
from pydantic import BaseModel
from typing import Dict, Optional

load_dotenv()

logger = logging.getLogger("rpg-agent")
logger.setLevel(logging.INFO)
logging.getLogger("livekit").setLevel(logging.CRITICAL)

# Models for Story API
class Game(BaseModel):
    title: str
    settings: Dict
    id: UUID
    world_id: UUID
    user_id: UUID
    character_id: UUID
    status: str
    created_at: datetime
    updated_at: datetime

class GameSummary(BaseModel):
    id: UUID
    turn_number: int
    summary_text: str

class GameData(BaseModel):
    world_description: str
    character_description: str
    character_appearance: Optional[str]
    image_style_prompt: Optional[str]
    intro: Optional[str]
    latest_summary: Optional[GameSummary]
    game: Game
    user_lang: str

async def get_game_data(game_id: str) -> Optional[GameData]:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{os.getenv('STORY_API_URL')}/games/{game_id}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return GameData.parse_obj(data)
                logger.error(f"Failed to fetch game data: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Error fetching game data: {e}")
        return None

async def send_to_imageGen_api(messages, turn_id, game_data: GameData):
    """Асинхронная генерация картинки для игровой сцены"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "pic_id": turn_id,
                "chat_history": messages[-1],
                "illustration_style": game_data.image_style_prompt,
                "main_character": game_data.character_appearance
            }
            logger.info("🎨 Sending image generation payload: %s", payload)
            async with session.post("https://storyimagegen-production.up.railway.app/process_chat",
                                    timeout=60,
                                    json=payload) as response:
                result = await response.json()
                logger.info("✅ Image generation completed")
                return result
    except Exception as e:
        logger.error(f"❌ Image generation failed: {e}")
        return None

async def save_next_turn_api(user_text: str, gm_text: str, game_id: str, image_url: str = "", image_prompt: str = ""):
    """Асинхронное сохранение хода в Story API"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "game_id": game_id,
                "player_text": user_text,
                "gm_response": gm_text,
                "image_url": image_url,
                "image_prompt": image_prompt
            }
            logger.info("💾 Saving turn to API: %s", payload)
            async with session.post(f"{os.getenv('STORY_API_URL')}/turns", json=payload) as response:
                if response.status == 200:
                    logger.info("✅ Turn saved successfully")
                else:
                    logger.error(f"❌ Turn save failed: {response.status}")
    except Exception as e:
        logger.error(f"❌ Turn save error: {e}")


class Assistant(Agent):
    def __init__(self, game_data: GameData, ctx: JobContext, user_lang: str):
        super().__init__(
            instructions=f"""
        Ты ведущий текстовой ролевой игры.
        Пользователь описывает свои действия, а ты описываешь реакцию мира.
        Отвечай на '{user_lang}' языке кратко, но увлекательно.
        
        У тебя есть доступ к игровым инструментам:
        - roll_dice: для броска костей при проверках
        - check_inventory: для проверки инвентаря игрока
        - save_game_state: для сохранения важных моментов игры
        
        Используй эти инструменты когда игрок пытается выполнить действия требующие проверок.

        Игровой мир:
        {game_data.world_description if game_data else 'Средневековый мир с магией'}

        Персонаж:
        {game_data.character_description if game_data else 'Неизвестный герой'}

        {f'Текущее состояние: {game_data.latest_summary.summary_text}' if game_data and game_data.latest_summary else ''}
        """
        )
        self.game_data = game_data
        self.ctx = ctx

    async def on_enter(self):
        logger.info("🎮 RPG Agent entered the session")
        # Генерируем приветствие
        greeting = self.game_data.latest_summary.summary_text if self.game_data and self.game_data.latest_summary else (
            self.game_data.intro if self.game_data and self.game_data.intro else "Добро пожаловать в игру! Опишите ваши действия."
        )
        logger.info(f"📢 Sending greeting: {greeting[:100]}...")
        await self.session.generate_reply(instructions=greeting)

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
        # В будущем здесь можно интегрировать с API для получения реального инвентаря
        return "В вашем инвентаре: меч, зелье лечения, 50 золотых монет, факел"

    @function_tool
    async def save_game_state(self, context: RunContext, action_description: str):
        """
        Сохраняет текущее состояние игры и действие игрока.
        
        Args:
            action_description: Описание действия игрока
        """
        logger.info(f"💾 Saving game state: {action_description[:50]}...")
        # Здесь можно интегрировать с Story API для сохранения ходов
        return f"Действие '{action_description}' сохранено в истории игры"

    async def handle_imagegen_api(self, gm_text, last_turn_id):
        """Фоновая обработка генерации и отправки картинки"""
        try:
            # Получаем историю чата для контекста
            chat_history = await self.session.get_chat_history()
            
            # Генерируем картинку асинхронно
            result = await send_to_imageGen_api(chat_history, last_turn_id, self.game_data)
            
            if result:
                image_url = result.get('image_url')
                image_prompt = result.get('illustration_prompt')

                if image_url:
                    # Сохраняем в userdata для логирования
                    self.ctx.proc.userdata["pic_url"] = image_url
                    self.ctx.proc.userdata["image_prompt"] = image_prompt
                    
                    # Отправляем картинку на фронтенд через DataChannel
                    await self.ctx.room.local_participant.publish_data(
                        image_url.encode('utf-8'),
                        reliable=True,
                        topic="topic1"  # Фронтенд слушает этот topic
                    )
                    logger.info(f"🖼️ Image sent to frontend: {image_url}")

                    # Сохраняем ход с картинкой если есть история
                    if len(chat_history) > 2:
                        user_text = chat_history[-2].content if len(chat_history) >= 2 else ""
                        await save_next_turn_api(user_text, gm_text, str(self.game_data.game.id), image_url, image_prompt)
                        
        except Exception as e:
            logger.error(f"❌ ImageGen API error: {e}")

    async def save_turn_background(self, user_text: str, agent_text: str):
        """Фоновое сохранение хода без картинки"""
        if self.game_data and self.game_data.game:
            await save_next_turn_api(user_text, agent_text, str(self.game_data.game.id))


def prewarm(proc: JobProcess):
    """Предзагрузка моделей"""
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("🔥 Models prewarmed")

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 Agent starting - Room: {ctx.room.name if ctx.room else 'None'}")
    
    await ctx.connect()
    logger.info(f"🔗 Connected to room: {ctx.room.name}")
    logger.info(f"🎯 Room participants: {len(ctx.room.remote_participants)}")
    
    # Логируем существующих участников
    for participant in ctx.room.remote_participants.values():
        logger.info(f"👤 Existing participant: {participant.identity}")
        for track_pub in participant.track_publications.values():
            logger.info(f"🎵 Existing track: {track_pub.sid} ({track_pub.source})")

    game_id = ctx.room.name
    game_data = await get_game_data(game_id)

    user_lang_code = "en"
    user_lang = "English"
    if game_data:
        if game_data.user_lang == "ru":
            user_lang = "Russian"
            user_lang_code = "ru"
        elif game_data.user_lang == "nl":
            user_lang = "Dutch"
            user_lang_code = "nl"

    assistant = Assistant(game_data, ctx, user_lang)

    try:
        session = AgentSession(
            stt=openai.STT(),
            llm=openai.LLM(model="gpt-4o-mini"),  # Используем более стабильную модель
            tts=openai.TTS(),
            vad=ctx.proc.userdata["vad"],
            turn_detection=MultilingualModel(),
        )
        logger.info("AgentSession created successfully")
    except Exception as e:
        logger.error(f"Failed to create AgentSession: {e}")
        return

    @session.on("user_state_changed")
    def on_user_state_changed(ev):
        logger.info(f"User state changed: {ev.old_state} -> {ev.new_state}")

    @session.on("agent_state_changed")
    def on_agent_state_changed(ev):
        logger.info(f"Agent state changed: {ev.old_state} -> {ev.new_state}")

    @session.on("participant_connected")
    def on_participant_connected(participant):
        logger.info(f"👤 Participant connected: {participant.identity}")
        logger.info(f"📊 Total participants now: {len(ctx.room.remote_participants) + 1}")

    @session.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        logger.info(f"🎵 Track subscribed: {track.sid} from participant {participant.identity}")
        logger.info(f"🎵 Track kind: {track.kind}, source: {track.source}")

    @session.on("user_speech_committed")
    def on_user_speech_committed(user_msg):
        nonlocal last_user_message
        logger.info(f"🎤 Player said: {user_msg.content}")
        last_user_message = user_msg.content

    @session.on("agent_speech_committed") 
    def on_agent_speech_committed(agent_msg):
        nonlocal turn_counter, last_user_message
        logger.info(f"🗣️ Agent said: {agent_msg.content}")
        
        # Асинхронно сохраняем ход в фоне (не блокируя диалог)
        if last_user_message:
            import asyncio
            asyncio.create_task(assistant.save_turn_background(last_user_message, agent_msg.content))
            
            # Увеличиваем счетчик ходов
            turn_counter += 1
            logger.info(f"📊 Turn #{turn_counter} completed")
            
            # Генерируем картинку при необходимости
            if should_generate_image(agent_msg.content, turn_counter):
                import uuid
                turn_id = str(uuid.uuid4())
                logger.info(f"🎨 Triggering image generation for turn #{turn_counter}")
                asyncio.create_task(assistant.handle_imagegen_api(agent_msg.content, turn_id))
            
            # Сбрасываем последнее сообщение пользователя
            last_user_message = ""

    @session.on("user_started_speaking")
    def on_user_started_speaking():
        logger.info("👂 Player started speaking")

    @session.on("user_stopped_speaking")
    def on_user_stopped_speaking():
        logger.info("🤫 Player stopped speaking")

    @session.on("function_calls_finished")
    def on_function_calls_finished(called_functions):
        for func in called_functions:
            logger.info(f"⚙️ Function called: {func.call_info.function_info.name}")

    @session.on("agent_started_speaking")  
    def on_agent_started_speaking():
        logger.info("🎙️ Agent started speaking")

    @session.on("agent_stopped_speaking")
    def on_agent_stopped_speaking():
        logger.info("🔇 Agent stopped speaking")

    # Убираем потенциально проблемные обработчики событий
    # @session.on("vad_state_changed")
    # def on_vad_state_changed(ev):
    #     logger.info(f"🎙️ VAD state changed: {ev}")

    # @session.on("stt_started") 
    # def on_stt_started():
    #     logger.info("📝 STT started processing")

    # @session.on("stt_finished")
    # def on_stt_finished():
    #     logger.info("📝 STT finished processing")

    # Переменные для отслеживания ходов и генерации картинок
    last_user_message = ""
    turn_counter = 0
    
    def should_generate_image(agent_text: str, turn_count: int) -> bool:
        """Определяет когда нужно генерировать картинку"""
        # Ключевые слова для генерации картинок
        image_keywords = ["вы видите", "перед вами", "появляется", "входите", "находите", 
                         "атакует", "сражение", "локация", "комната", "пещера", "лес"]
        
        # Генерируем картинку каждые 3 хода или при ключевых словах
        has_keywords = any(keyword in agent_text.lower() for keyword in image_keywords)
        periodic_generation = (turn_count % 3 == 0) and turn_count > 0
        
        return has_keywords or periodic_generation

    ctx.add_shutdown_callback(lambda: logger.info("Session ended."))

    logger.info(f"Starting agent session with language: {user_lang} ({user_lang_code})")
    logger.info(f"STT language: {user_lang_code}")
    logger.info(f"TTS settings: speed={0.5 if user_lang_code == 'ru' else 1.0}")
    
    try:
        await session.start(agent=assistant, room=ctx.room)
        logger.info("✅ Agent session started successfully")
        
    except Exception as e:
        logger.error(f"Failed to start agent session: {e}")
        return



if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        shutdown_process_timeout=5,
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm
    ))
