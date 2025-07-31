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

class Turn(BaseModel):
    id: UUID
    game_id: UUID
    turn_number: int
    player_text: Optional[str]
    gm_response: Optional[str]
    image_url: Optional[str]
    image_prompt: Optional[str]
    created_at: datetime

class GameData(BaseModel):
    world_description: str
    character_description: str
    character_appearance: Optional[str]
    image_style_prompt: Optional[str]
    intro: Optional[str]
    latest_summary: Optional[GameSummary]
    game: Game
    user_lang: str
    turns: Optional[list[Turn]] = []

async def get_game_data(game_id: str) -> Optional[GameData]:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{os.getenv('STORY_API_URL')}/api/v1/games/{game_id}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return GameData.parse_obj(data)
                logger.error(f"Failed to fetch game data: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Error fetching game data: {e}")
        return None

async def send_to_imageGen_api(message_data, turn_id, game_data: GameData):
    """Асинхронная генерация картинки для игровой сцены"""
    try:
        async with aiohttp.ClientSession() as session:
            # Исправляем формат для соответствия API схеме
            payload = {
                "chat_history": message_data.get("content", "") if isinstance(message_data, dict) else str(message_data),
                "illustration_style": game_data.image_style_prompt,
                "main_character": game_data.character_appearance,
                "file_name": turn_id  # Используем turn_id как file_name
            }
            logger.info("🎨 Sending image generation payload: %s", payload)
            async with session.post("https://storyimagegen-production.up.railway.app/process_chat",
                                    timeout=60,
                                    json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info("✅ Image generation completed")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Image generation failed with status {response.status}: {error_text}")
                    return None
    except Exception as e:
        logger.error(f"❌ Image generation failed: {e}")
        return None

async def generate_summary_api(game_id: str) -> bool:
    """Генерирует саммари через API"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{os.getenv('STORY_API_URL')}/api/v1/summary/{game_id}/generate"
            async with session.post(url) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"✅ Summary generated for game {game_id}: turn {result.get('turn_number', 'unknown')}")
                    return True
                else:
                    logger.error(f"❌ Summary generation failed: {response.status}")
                    return False
    except Exception as e:
        logger.error(f"❌ Summary generation error: {e}")
        return False

async def save_next_turn_api(user_text: str, gm_text: str, game_id: str, image_url: str = "", image_prompt: str = ""):
    """Асинхронное сохранение хода в Story API"""
    try:
        # Обеспечиваем правильный формат данных для API
        # Исправляем массив в строку если необходимо
        if isinstance(user_text, list):
            user_text = user_text[0] if len(user_text) > 0 else ""
        if isinstance(gm_text, list):
            gm_text = gm_text[0] if len(gm_text) > 0 else ""
            
        async with aiohttp.ClientSession() as session:
            payload = {
                "game_id": game_id,
                "player_text": str(user_text),  # Убеждаемся что это строка
                "gm_response": str(gm_text),    # Убеждаемся что это строка
                "gm_prompt": f"System prompt for turn: {user_text}",  # Добавляем обязательное поле
                "image_url": image_url or None,      # API ожидает null вместо пустой строки
                "image_prompt": image_prompt or None # API ожидает null вместо пустой строки
            }
            logger.info("💾 Saving turn to API: %s", payload)
            async with session.post(f"{os.getenv('STORY_API_URL')}/api/v1/turns", json=payload) as response:
                if response.status == 200:
                    logger.info("✅ Turn saved successfully")
                else:
                    logger.error(f"❌ Turn save failed: {response.status}")
    except Exception as e:
        logger.error(f"❌ Turn save error: {e}")



class Assistant(Agent):
    def __init__(self, game_data: GameData, ctx: JobContext, user_lang: str):
        # Формируем инструкции с учетом истории игры
        instructions = f"""
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
        
        super().__init__(instructions=instructions.strip())
        self.game_data = game_data
        self.ctx = ctx
        self.turn_counter = 0  # Счетчик ходов для автоматической генерации саммари

    async def on_enter(self):
        logger.info("🎮 RPG Agent entered the session")
        
        # Отправляем последнюю картинку на фронт если это продолжение игры
        await self._send_latest_image_to_frontend()
        
        # Получаем приветствие/саммари но НЕ используем session.generate_reply() чтобы не загрязнять chat context
        greeting = self.game_data.latest_summary.summary_text if self.game_data and self.game_data.latest_summary else (
            self.game_data.intro if self.game_data and self.game_data.intro else "Добро пожаловать в игру! Опишите ваши действия."
        )
        
        # Если есть latest_summary - это продолжение игры
        if self.game_data and self.game_data.latest_summary:
            logger.info(f"📖 Playing latest summary for continuing game: {greeting[:100]}...")
        else:
            logger.info(f"📢 Prepared intro greeting for new game: {greeting[:100]}...")
            
        # Отправляем приветствие/саммори через session.say()
        try:
            logger.info(f"🔍 Checking session availability: {hasattr(self, 'session')}")
            if hasattr(self, 'session') and self.session:
                await self.session.say(greeting)
                logger.info("🔊 Greeting/Summary played via session.say()")
            else:
                logger.warning("⚠️ Session not available in on_enter, skipping TTS playback")
        except Exception as e:
            logger.error(f"❌ Error in on_enter TTS playback: {e}")
            logger.info("🎯 Continuing without TTS playback...")
            
    async def _send_latest_image_to_frontend(self):
        """Отправляет последнюю картинку на фронтенд при старте сессии"""
        try:
            if not self.game_data or not self.game_data.turns:
                logger.info("📸 No turns available, no image to send")
                return
                
            # Находим последний ход с картинкой
            latest_turn_with_image = None
            for turn in reversed(self.game_data.turns):
                if turn.image_url:
                    latest_turn_with_image = turn
                    break
                    
            if not latest_turn_with_image:
                logger.info("📸 No image found in recent turns")
                return
                
            # Небольшая задержка чтобы участники успели подключиться
            await asyncio.sleep(1)
            
            # Проверяем что участники подключены
            participants_count = len(self.ctx.room.remote_participants)
            logger.info(f"🔍 Room has {participants_count} remote participants before sending startup image")
            
            # Отправляем картинку через DataChannel
            image_url = latest_turn_with_image.image_url
            await self.ctx.room.local_participant.publish_data(
                image_url.encode('utf-8'),
                reliable=True,
                topic="topic1"
            )
            logger.info(f"🖼️ Latest image sent to frontend on session start: {image_url}")
            
        except Exception as e:
            logger.error(f"❌ Failed to send latest image: {e}")

    async def on_session_end(self):
        """Вызывается при завершении игровой сессии"""
        logger.info("🏁 Game session ending - generating final summary")
        try:
            if self.game_data and self.game_data.game:
                summary_success = await generate_summary_api(str(self.game_data.game.id))
                if summary_success:
                    logger.info("✅ Final summary generated successfully on session end")
                else:
                    logger.warning("⚠️ Failed to generate final summary on session end")
            else:
                logger.info("📝 No game data available for final summary generation")
        except Exception as e:
            logger.error(f"❌ Error generating final summary on session end: {e}")

    async def on_user_turn_completed(self, turn_ctx, new_message):
        """Вызывается когда пользователь закончил говорить, до ответа агента"""
        logger.info(f"🎤 User turn completed: {new_message.content}")
        
        # Диагностика контекста
        logger.info(f"🔍 turn_ctx type: {type(turn_ctx)}")
        logger.info(f"🔍 turn_ctx attributes: {dir(turn_ctx)}")
        
        # Пробуем правильный способ получения сообщений из ChatContext
        try:
            items = turn_ctx.items if hasattr(turn_ctx, 'items') else []
            logger.info(f"🔍 turn_ctx.items: {len(items)} items")
            for i, item in enumerate(items):
                logger.info(f"🔍 Item {i}: {type(item)} - {getattr(item, 'content', 'no content')[:50]}...")
        except Exception as e:
            logger.error(f"❌ Error getting turn_ctx items: {e}")
        
        # Проверяем new_message структуру
        logger.info(f"🔍 new_message type: {type(new_message)}")
        logger.info(f"🔍 new_message.content: {new_message.content}")
        logger.info(f"🔍 new_message attributes: {dir(new_message)}")
        
        # Сохраняем контекст и сообщение для дальнейшего использования
        # Исправляем формат - берем первый элемент если это массив
        user_content = new_message.content
        if isinstance(user_content, list) and len(user_content) > 0:
            user_content = user_content[0]
        elif isinstance(user_content, list):
            user_content = ""
            
        self.last_user_message = str(user_content)
        self.current_turn_ctx = turn_ctx
        logger.info(f"🔧 Processed user message: '{self.last_user_message}'")
        
        # Убираем немедленное сохранение - только задержанное с правильным ответом агента
        # logger.info("💾 Attempting immediate turn save...")
        # await self._immediate_turn_save()
        
        # Только одно задержанное сохранение с полным ответом агента
        # Предотвращаем множественные вызовы с помощью флага
        if not hasattr(self, '_save_in_progress') or not self._save_in_progress:
            self._save_in_progress = True
            import asyncio
            asyncio.create_task(self._delayed_turn_save_with_context())
        
    async def _delayed_turn_save_with_context(self):
        """Задержанное сохранение хода после генерации ответа агента"""
        try:
            # Ждем больше времени чтобы агент сгенерировал и добавил ответ в контекст
            await asyncio.sleep(8)
            
            # Используем сохраненный контекст чата
            if hasattr(self, 'current_turn_ctx') and self.current_turn_ctx:
                # В turn_ctx история сообщений хранится в items
                messages = getattr(self.current_turn_ctx, 'items', [])
                
                if len(messages) >= 2:
                    # Ищем последнее пользовательское и агентское сообщение
                    user_msg = getattr(self, 'last_user_message', '')
                    
                    # Упрощенная логика: берем последнее сообщение от assistant
                    # После 8 секунд задержки это должен быть правильный ответ на текущий запрос
                    agent_msg = ""
                    for msg in reversed(messages):
                        if hasattr(msg, 'role') and msg.role == 'assistant':
                            content = msg.content
                            if isinstance(content, list):
                                content = content[0] if len(content) > 0 else ""
                            agent_msg = str(content)
                            break
                    
                    logger.info(f"🔍 Found agent message: '{agent_msg[:100]}...' from {len(messages)} total messages")
                    
                    if user_msg and agent_msg:
                        logger.info(f"💾 Context-based turn save - User: '{user_msg[:50]}...', Agent: '{str(agent_msg)[:50]}...'")
                        await self._save_and_generate_image(user_msg, agent_msg)
                    else:
                        logger.warning(f"⚠️ Missing messages - user: {bool(user_msg)}, agent: {bool(agent_msg)}")
                        logger.info(f"📝 Available messages: {len(messages)}")
                        # Логируем все сообщения для отладки
                        for i, msg in enumerate(messages):
                            logger.info(f"📝 Message {i}: role={getattr(msg, 'role', 'unknown')}, content={str(getattr(msg, 'content', ''))[:100]}...")
                        
                        # Попробуем просто с пользовательским сообщением
                        if user_msg:
                            await self._save_and_generate_image(user_msg, "Agent response processing...")
                else:
                    logger.warning(f"⚠️ Not enough messages in context: {len(messages) if messages else 0}")
            else:
                logger.warning("⚠️ No turn context available for delayed save")
                
        except Exception as e:
            logger.error(f"❌ Delayed turn save error: {e}")
        finally:
            # Сбрасываем флаг сохранения
            self._save_in_progress = False
            
    # Удалены неиспользуемые методы _immediate_turn_save и _delayed_turn_save

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
        
        # Убираем дополнительные сохранения из function tools - основное сохранение происходит в on_user_turn_completed
        # await self._trigger_turn_save_and_image("dice roll action")
        
        return f"Результат броска d{sides}: {result}"

    @function_tool 
    async def check_inventory(self, context: RunContext):
        """
        Показывает инвентарь игрока.
        """
        logger.info("🎒 Checking player inventory")
        
        # Убираем дополнительные сохранения из function tools
        # await self._trigger_turn_save_and_image("inventory check")
        
        return "В вашем инвентаре: меч, зелье лечения, 50 золотых монет, факел"

    @function_tool
    async def save_game_state(self, context: RunContext, action_description: str):
        """
        Сохраняет текущее состояние игры и действие игрока.
        
        Args:
            action_description: Описание действия игрока
        """
        logger.info(f"💾 Saving game state: {action_description[:50]}...")
        
        # Убираем дублирующие сохранения из function tools - основное сохранение происходит в on_user_turn_completed
        # Сохранение и генерация картинки будут выполнены автоматически после завершения ответа агента
        logger.info("🛠️ Function tool executed - turn will be saved by main handler")
            
        return f"Действие '{action_description}' сохранено в истории игры"

    async def handle_imagegen_api(self, gm_text, last_turn_id, user_text):
        """Фоновая обработка генерации и отправки картинки"""
        image_url = ""
        image_prompt = ""
        
        try:
            # Конвертируем сообщение в правильный формат для API
            if isinstance(gm_text, list):
                gm_text = gm_text[0] if len(gm_text) > 0 else ""
            gm_text = str(gm_text)
            
            # Создаем простую структуру для API (не объект ChatMessage)
            chat_history_for_api = {"content": gm_text}
            
            # Генерируем картинку асинхронно
            result = await send_to_imageGen_api(chat_history_for_api, last_turn_id, self.game_data)
            
            if result:
                image_url = result.get('image_url', '')
                image_prompt = result.get('illustration_prompt', '')

                if image_url:
                    # Сохраняем в userdata для логирования
                    self.ctx.proc.userdata["pic_url"] = image_url
                    self.ctx.proc.userdata["image_prompt"] = image_prompt
                    
                    # Проверяем, есть ли участники в комнате перед отправкой
                    participants_count = len(self.ctx.room.remote_participants)
                    logger.info(f"🔍 Room has {participants_count} remote participants")
                    
                    # Отправляем картинку на фронтенд через DataChannel
                    try:
                        await self.ctx.room.local_participant.publish_data(
                            image_url.encode('utf-8'),
                            reliable=True,
                            topic="topic1"  # Фронтенд слушает этот topic
                        )
                        logger.info(f"🖼️ Image sent to frontend via DataChannel: {image_url}")
                        logger.info(f"📡 DataChannel message size: {len(image_url.encode('utf-8'))} bytes")
                    except Exception as e:
                        logger.error(f"❌ Failed to send image via DataChannel: {e}")
        except Exception as e:
            logger.error(f"❌ ImageGen API error: {e}")
        
        # ВСЕГДА сохраняем ход (с картинкой если есть, без если нет)
        try:
            if self.game_data and self.game_data.game:
                await save_next_turn_api(user_text, gm_text, str(self.game_data.game.id), image_url, image_prompt)
                logger.info("📊 Turn saved with image data")
                
                # Увеличиваем счетчик ходов и проверяем нужно ли генерировать саммари
                self.turn_counter += 1
                logger.info(f"🔢 Turn counter: {self.turn_counter}")
                
                # Генерируем саммари каждые 6 ходов
                if self.turn_counter % 6 == 0:
                    logger.info(f"📝 Generating summary after {self.turn_counter} turns")
                    summary_success = await generate_summary_api(str(self.game_data.game.id))
                    if summary_success:
                        logger.info("✅ Auto-summary generation completed")
                    else:
                        logger.warning("⚠️ Auto-summary generation failed")
                        
        except Exception as e:
            logger.error(f"❌ Turn save error: {e}")

    async def save_turn_background(self, user_text: str, agent_text: str):
        """Фоновое сохранение хода без картинки"""
        if self.game_data and self.game_data.game:
            await save_next_turn_api(user_text, agent_text, str(self.game_data.game.id))

    async def _save_and_generate_image(self, user_message: str, agent_message: str):
        """Сохраняет ход и генерирует картинку при необходимости"""  
        try:
            # Исправляем формат сообщений - конвертируем массивы в строки
            if isinstance(agent_message, list):
                agent_message = agent_message[0] if len(agent_message) > 0 else ""
            if isinstance(user_message, list):
                user_message = user_message[0] if len(user_message) > 0 else ""
                
            # Убеждаемся что это строки
            agent_message = str(agent_message)
            user_message = str(user_message)
            
            logger.info(f"💾 Saving turn - User: '{user_message[:50]}...', Agent: '{agent_message[:50]}...'")
            
            # НЕ сохраняем ход сразу - ждем генерации картинки
            # import asyncio
            # asyncio.create_task(self.save_turn_background(user_message, agent_message))
            # logger.info("📊 Turn saved successfully")
            
            # Генерируем картинку на каждом ходе - сохранение произойдет там
            import uuid
            turn_id = str(uuid.uuid4())
            logger.info("🎨 Image generation triggered for every turn")
            # Используем сохраненное пользовательское сообщение
            user_msg = getattr(self, 'last_user_message', user_message)
            asyncio.create_task(self.handle_imagegen_api(agent_message, turn_id, user_msg))
                
        except Exception as e:
            logger.error(f"❌ Save and generate error: {e}")

    # Удален неиспользуемый метод _trigger_turn_save_and_image


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
            min_endpointing_delay=1.2,  # Увеличено с 0.4 до 1.2 сек для предотвращения разбиения сообщений
            max_endpointing_delay=8.0,  # Увеличено с 6.0 до 8.0 сек
        )
        logger.info("AgentSession created with turn detection config: min_delay=1.2s, max_delay=8.0s")
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

    # Основные события теперь обрабатываются через on_user_turn_completed в Assistant классе
    # Оставляем только вспомогательные события для отладки

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
    
    # События для отладки (могут не срабатывать в новой архитектуре)
    @session.on("user_message") 
    def on_user_message(msg):
        logger.info(f"🔍 Debug: user_message event - {msg}")

    @session.on("agent_message")
    def on_agent_message(msg):
        logger.info(f"🔍 Debug: agent_message event - {msg}")

    @session.on("agent_started_speaking")  
    def on_agent_started_speaking():
        logger.info("🎙️ Agent started speaking")

    @session.on("agent_stopped_speaking")
    def on_agent_stopped_speaking():
        logger.info("🔇 Agent stopped speaking")
        
    # Пробуем разные варианты событий для сообщений
    @session.on("user_speech_transcribed")
    def on_user_speech_transcribed(msg):
        logger.info(f"📝 User speech transcribed: {msg}")

    @session.on("agent_speech_synthesized") 
    def on_agent_speech_synthesized(msg):
        logger.info(f"🔊 Agent speech synthesized: {msg}")

    @session.on("conversation_turn_finished")
    def on_conversation_turn_finished(turn):
        logger.info(f"🔄 Conversation turn finished: {turn}")
        
    # Попробуем отловить все неизвестные события
    def log_all_events(event_name, *args, **kwargs):
        logger.info(f"🔍 Unknown event: {event_name} with args: {args}")
        
    # Добавляем универсальный обработчик (если поддерживается)
    try:
        session.on("*", log_all_events)
    except:
        pass

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

    # Переменные для отслеживания состояния агента
    assistant.turn_counter = 0

    # Добавляем callback для генерации финального саммари при завершении сессии
    async def on_session_shutdown():
        logger.info("Session ended.")
        await assistant.on_session_end()
    
    ctx.add_shutdown_callback(on_session_shutdown)

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
