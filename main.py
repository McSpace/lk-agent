import asyncio
import json
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
    ConversationItemAddedEvent,
)
from livekit.agents.llm.llm import ChatChunk
from livekit.agents.llm import function_tool
from livekit.plugins import deepgram, openai, silero, cartesia, google, elevenlabs
from livekit.plugins.elevenlabs.tts import VoiceSettings
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from dotenv import load_dotenv
import livekit.api

import logging
from uuid import UUID
from pydantic import BaseModel
from typing import Dict, Optional

from voice_factory import VoiceComponentFactory

load_dotenv()

logger = logging.getLogger("rpg-agent")
logger.setLevel(logging.INFO)
logging.getLogger("livekit").setLevel(logging.INFO)

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

class UserVoiceSettings(BaseModel):
    language: str = "en"
    speech_speed: float = 1.0

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
    def __init__(self, game_data: GameData, ctx: JobContext, user_settings: UserVoiceSettings):
        # Получаем язык из настроек пользователя
        user_lang = self._get_language_name(user_settings.language)
        
        # Формируем инструкции с учетом истории игры
        instructions = f"""
        Ты ведущий текстовой ролевой игры.
        Пользователь описывает свои действия, а ты описываешь реакцию мира.
        Отвечай на '{user_lang}' языке кратко, но увлекательно.
        
        У тебя есть доступ к игровым инструментам:
        - roll_dice: для броска костей при проверках
        - check_inventory: для проверки инвентаря игрока
        
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
        self.pending_user_message = None  # Хранение пользовательского сообщения для раннего сохранения
        self.early_save_triggered = False  # Флаг для предотвращения дублирования сохранений
        
        # Настройки голоса пользователя
        self.voice_settings = user_settings
        
        # Инициализируем текущий TTS компонент
        self.current_tts = VoiceComponentFactory.create_tts(
            self.voice_settings.language, 
            self.voice_settings.speech_speed
        )
        
        # Инициализируем fallback для updated_instructions
        self.updated_instructions = None
        
        # Обновление инструкций будет выполнено в on_enter() так как это async операция
        
        logger.info(f"🎛️ Voice settings initialized: language='{self.voice_settings.language}', speed={self.voice_settings.speech_speed}")
        logger.info(f"🔊 Initial TTS component created for language: {self.voice_settings.language}")

    def _get_language_name(self, lang_code: str) -> str:
        """Получить полное название языка по коду"""
        lang_names = {
            "en": "English",
            "ru": "Russian", 
            "nl": "Dutch",
            "fr": "French",
            "es": "Spanish"
        }
        return lang_names.get(lang_code, "English")

    async def update_llm_instructions(self):
        """Обновляет LLM инструкции с текущим языком используя официальный API LiveKit 1.x"""
        try:
            user_lang = self._get_language_name(self.voice_settings.language)
            
            # Пересоздаем инструкции с обновленным языком
            updated_instructions = f"""
            Ты ведущий текстовой ролевой игры.
            Пользователь описывает свои действия, а ты описываешь реакцию мира.
            Отвечай на '{user_lang}' языке кратко, но увлекательно.
            
            У тебя есть доступ к игровым инструментам:
            - roll_dice: для броска костей при проверках
            - check_inventory: для проверки инвентаря игрока
            
            Используй эти инструменты когда игрок пытается выполнить действия требующие проверок.

            Игровой мир:
            {self.game_data.world_description if self.game_data else 'Средневековый мир с магией'}

            Персонаж:
            {self.game_data.character_description if self.game_data else 'Неизвестный герой'}

            {f'Текущее состояние: {self.game_data.latest_summary.summary_text}' if self.game_data and self.game_data.latest_summary else ''}
            """.strip()
            
            # Используем официальный API LiveKit 1.x для обновления инструкций - АСИНХРОННО
            await self.update_instructions(updated_instructions)
            logger.info(f"🧠 LLM instructions updated using official API for language: {user_lang}")
            
        except Exception as e:
            logger.error(f"❌ Failed to update LLM instructions using official API: {e}")
            # Fallback - сохраняем инструкции для ручной обработки в llm_node
            self.updated_instructions = updated_instructions
            logger.info(f"🔄 Fallback: storing instructions for manual llm_node processing")

    async def recreate_tts_component(self):
        """Пересоздает TTS компонент с новыми настройками языка"""
        try:
            logger.info(f"🔊 Recreating TTS component for language: {self.voice_settings.language}")
            
            # Создаем новый TTS компонент через фабрику
            new_tts = VoiceComponentFactory.create_tts(
                self.voice_settings.language, 
                self.voice_settings.speech_speed
            )
            
            # Сохраняем ссылку для использования в tts_node
            self.current_tts = new_tts
            logger.info(f"🎯 New TTS component created and stored")
            
            return new_tts
            
        except Exception as e:
            logger.error(f"❌ Failed to recreate TTS component: {e}")
            return None

    async def update_voice_settings(self, language: str, speech_speed: float):
        """Обновить настройки голоса в runtime"""
        logger.info(f"🔄 Updating voice settings: {language}, speed={speech_speed}")
        
        # Валидируем настройки через фабрику
        validated_language, validated_speed = VoiceComponentFactory.validate_settings(language, speech_speed)
        
        # Сохраняем старый язык для сравнения
        old_language = self.voice_settings.language
        
        # Обновляем настройки
        self.voice_settings.language = validated_language
        self.voice_settings.speech_speed = validated_speed
        
        # Если язык изменился, обновляем LLM инструкции и пересоздаем TTS
        if old_language != validated_language:
            logger.info(f"🌐 Language changed from {old_language} to {validated_language}")
            await self.update_llm_instructions()
            await self.recreate_tts_component()
        
        logger.info(f"✅ Voice settings updated: language='{self.voice_settings.language}', speed={self.voice_settings.speech_speed}")

    async def on_enter(self):
        logger.info("🎮 RPG Agent entered the session")
        
        # Обновляем инструкции с правильным языком при входе в сессию
        await self.update_llm_instructions()
        
        # Отправляем последнюю картинку на фронт если это продолжение игры
        await self._send_latest_image_to_frontend()
            
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

    # async def tts_node(self, text, model_settings):
    #     """Переопределенный tts_node для использования динамически созданного TTS компонента"""
    #     logger.info(f"🔊 tts_node called with language='{self.voice_settings.language}', speed={self.voice_settings.speech_speed}")
    #     logger.info(f"🔍 Text to synthesize: '{text[:50]}...'")
        
    #     try:
    #         # Используем текущий TTS компонент (обновляется в recreate_tts_component)
    #         if hasattr(self, 'current_tts') and self.current_tts:
    #             logger.info(f"🎯 Using current TTS component: {type(self.current_tts).__name__}")
                
    #             # Правильно вызываем synthesize - передаем только текст
    #             synthesis_stream = self.current_tts.synthesize(text)
    #             logger.info(f"🔄 Got synthesis stream: {type(synthesis_stream)}")
                
    #             async for frame in synthesis_stream:
    #                 yield frame
                    
    #             logger.info("✅ TTS synthesis completed successfully")
    #         else:
    #             logger.warning("⚠️ No current TTS component, falling back to default")
    #             # Fallback на дефолтный TTS сразу
    #             async for frame in Agent.default.tts_node(self, text, model_settings):
    #                 yield frame
                
    #     except Exception as e:
    #         logger.error(f"❌ TTS node error: {e}")
    #         logger.error(f"📍 Error details: {type(e).__name__}: {str(e)}")
    #         # Fallback на дефолтный TTS
    #         logger.info("🔄 Falling back to default TTS")
    #         try:
    #             async for frame in Agent.default.tts_node(self, text, model_settings):
    #                 yield frame
    #         except Exception as fallback_error:
    #             logger.error(f"❌ Fallback TTS also failed: {fallback_error}")
    #             raise

    async def llm_node(self, chat_ctx, tools, model_settings):
        """Переопределенный llm_node для раннего перехвата ответа агента и обновления языка"""
        logger.info("🧠 llm_node started - intercepting LLM chunks")
        logger.info(f"🔍 Initial state: pending_user_message={bool(self.pending_user_message)}, early_save_triggered={self.early_save_triggered}")
        logger.info(f"🌐 Current language: {self.voice_settings.language}")
        
        try:
            # С официальным update_instructions() API нам не нужно вручную модифицировать chat context
            # Инструкции уже обновлены через update_instructions() в update_llm_instructions()
            logger.info(f"🔄 Using current agent instructions with language: {self.voice_settings.language}")
            
            # Проверяем есть ли fallback инструкции (если официальный API не сработал)
            if hasattr(self, 'updated_instructions') and self.updated_instructions:
                logger.warning(f"⚠️ Found fallback instructions - official API might have failed")
                # Можно попробовать применить fallback, но обычно не нужно
            else:
                logger.info(f"✅ Agent instructions should be properly updated via official API")
            
            # Простое накопление чанков текущего вызова
            current_response_chunks = []
            is_last_chunk = False
            chunk_count = 0
            
            logger.info("🔄 Starting chunk iteration...")
            # Получаем поток чанков от базового LLM узла
            async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
                chunk_count += 1
                # logger.info(f"📦 Processing chunk #{chunk_count}: type={type(chunk).__name__}")
                
                # Передаем чанк дальше в TTS без прерывания потока
                yield chunk
                
                # Накапливаем текст для раннего сохранения
                if isinstance(chunk, ChatChunk):
                    if chunk.delta:
                        # Извлекаем текст из ChoiceDelta объекта
                        delta_text = ""
                        if hasattr(chunk.delta, 'content') and chunk.delta.content:
                            delta_text = chunk.delta.content
                        
                        if delta_text:
                            current_response_chunks.append(delta_text)
                            # logger.info(f"📝 Added delta text: '{delta_text[:50]}...'")
                        else:
                            logger.info(f"📝 No content in delta: {type(chunk.delta)}")
                        
                    # Проверяем является ли это последним чанком
                    if chunk.usage is not None:
                        is_last_chunk = True
                        logger.info("🎯 Last LLM chunk detected via chunk.usage")
                        logger.info(f"📊 Usage info: {chunk.usage}")
                else:
                    # Для строковых чанков (простые LLM ответы)
                    current_response_chunks.append(str(chunk))
                    is_last_chunk = True
                    #logger.info(f"🎯 String chunk received - treating as last: '{str(chunk)[:50]}...'")
            
            logger.info(f"✅ Chunk iteration completed. Total chunks: {chunk_count}")
            
            # Получаем полный ответ этого вызова
            full_response = ''.join(current_response_chunks)
            logger.info(f"📝 llm_node completed - response: '{full_response[:100]}...' (length: {len(full_response)})")
            
            # Логируем все условия для сохранения
            logger.info(f"🔍 Save conditions check:")
            logger.info(f"  is_last_chunk: {is_last_chunk}")
            logger.info(f"  pending_user_message: {bool(self.pending_user_message)}")
            logger.info(f"  early_save_triggered: {self.early_save_triggered}")
            
            # Если это последний чанк И у нас есть pending user message - сохраняем сразу
            if is_last_chunk and self.pending_user_message and not self.early_save_triggered:
                self.early_save_triggered = True
                logger.info(f"📄 Full agent response: {full_response}")
                logger.info("⚡ Immediate save triggered - calling _save_turn_immediately")
                
                # Запускаем сохранение и генерацию изображения немедленно
                import asyncio
                asyncio.create_task(self._save_turn_immediately(self.pending_user_message, full_response))
                self.pending_user_message = None  # Очищаем чтобы избежать дублирования
            else:
                logger.info("⏭️ Save conditions not met - skipping save")
                
        except Exception as e:
            logger.error(f"❌ Exception in llm_node: {e}")
            logger.error(f"📍 Exception details: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            raise


    async def on_user_turn_completed(self, turn_ctx, new_message):
        """Вызывается когда пользователь закончил говорить, до ответа агента"""
        logger.info(f"🎤 User turn completed: {new_message.content}")
        
        # Извлекаем пользовательское сообщение
        user_content = new_message.content
        if isinstance(user_content, list) and len(user_content) > 0:
            user_content = user_content[0]
        elif isinstance(user_content, list):
            user_content = ""
            
        # Сохраняем для использования в llm_node
        self.pending_user_message = str(user_content)
        self.early_save_triggered = False  # Сбрасываем флаг для нового хода
        logger.info(f"💬 User message stored for llm_node early capture: '{self.pending_user_message[:100]}...'")
        logger.info("⏳ Waiting for llm_node to capture complete response...")
        
    async def _save_turn_immediately(self, user_message: str, agent_message: str):
        """Немедленное сохранение хода с точными данными из conversation_item_added событий"""
        try:
            logger.info(f"⚡ Immediate turn save triggered by conversation event")
            logger.info(f"  👤 User: '{user_message[:50]}...'")
            logger.info(f"  🤖 Agent: '{agent_message[:50]}...'")
            
            # Прямо вызываем сохранение и генерацию изображения
            await self._save_and_generate_image(user_message, agent_message)
            
        except Exception as e:
            logger.error(f"❌ Immediate turn save error: {e}")

    # Старые методы с задержками удалены - используем событийную модель

    # Временно отключаем function tools для диагностики
    # @function_tool
    # async def roll_dice(self, context: RunContext, sides: int = 20):
    #     """
    #     Бросает игральную кость для определения результата действий.
    #     
    #     Args:
    #         sides: Количество граней на кости (по умолчанию 20)
    #     """
    #     import random
    #     result = random.randint(1, sides)
    #     logger.info(f"🎲 Dice roll: {result} (d{sides})")
    #     
    #     return f"Результат броска d{sides}: {result}"

    # @function_tool 
    # async def check_inventory(self, context: RunContext):
    #     """
    #     Показывает инвентарь игрока.
    #     """
    #     logger.info("🎒 Checking player inventory")
    #     
    #     return "В вашем инвентаре: меч, зелье лечения, 50 золотых монет, факел"

    # @function_tool
    # async def save_game_state(self, context: RunContext, action_description: str):
    #     """
    #     Сохраняет текущее состояние игры и действие игрока.
    #     
    #     Args:
    #         action_description: Описание действия игрока
    #     """
    #     logger.info(f"💾 Saving game state: {action_description[:50]}...")
    #     logger.info("🛠️ Function tool executed - turn will be saved by main handler")
    #         
    #     return f"Действие '{action_description}' сохранено в истории игры"

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

    # Создаем дефолтные настройки пользователя 
    # ВАЖНО: user settings имеют приоритет над game_data.user_lang
    user_voice_settings = UserVoiceSettings()
    if game_data:
        # Используем язык из данных игры как дефолтный ТОЛЬКО если он поддерживается
        default_lang = game_data.user_lang if game_data.user_lang in VoiceComponentFactory.get_supported_languages() else "en"
        user_voice_settings.language = default_lang
        logger.info(f"🌐 Default language from game data: {user_voice_settings.language}")
        logger.info(f"📋 Note: User settings via DataChannel will override this default")
    
    assistant = Assistant(game_data, ctx, user_voice_settings)

    try:
        session = AgentSession(
            stt=openai.STT(),
            llm=openai.LLM(model="gpt-4o-mini"),  # Используем более стабильную модель
            tts=openai.TTS(),  # Временно используем дефолтный TTS для диагностики
            # tts= VoiceComponentFactory.create_tts(
            #     user_voice_settings.language, 
            #     1.0  # Используем дефолтную скорость
            # ),
            # tts=elevenlabs.TTS(
            #     model="eleven_multilingual_v2",
            #     voice_id="8JVbfL6oEdmuxKn5DK2C",#"4YoYFeikaSRSlzRu5Ga0",
            #     # voice_settings=VoiceSettings(
            #     #         stability=0.40,
            #     #         similarity_boost=0.50,
            #     #         style=0.0,
            #     #         use_speaker_boost=True
            #     #     )
            #     ),
            
            vad=ctx.proc.userdata["vad"],
            turn_detection=MultilingualModel(),
            min_endpointing_delay=1.2,  # Увеличено с 0.4 до 1.2 сек для предотвращения разбиения сообщений
            max_endpointing_delay=8.0,  # Увеличено с 6.0 до 8.0 сек
        )
        logger.info("AgentSession created with turn detection config: min_delay=1.2s, max_delay=8.0s")
        
    except Exception as e:
        logger.error(f"Failed to create AgentSession: {e}")
        return

    @session.on("error")
    def on_error(event):
        logger.error(f"Session error: {event.error}")
        logger.error(f"Error source: {event.source}")
        logger.error(f"Is recoverable: {event.error.recoverable}")
        if not event.error.recoverable:
            logger.error("Unrecoverable error detected")

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

    # Убираем старый обработчик conversation_item_added - теперь используем llm_node для раннего перехвата
    # @session.on("conversation_item_added")
    # def on_conversation_item_added(event: ConversationItemAddedEvent):
    #     """Старый событийный обработчик - заменен на llm_node перехват"""
    #     logger.info("🔍 conversation_item_added event (replaced by llm_node early capture)")

    # DataChannel обработчик для получения настроек от фронтенда
    @ctx.room.on("data_received")
    def on_data_received(data):
        """Обработка DataChannel сообщений от фронтенда"""
        try:
            # Декодируем JSON данные
            message = json.loads(data.data.decode('utf-8'))
            logger.info(f"📡 DataChannel message received: {message}")
            
            # Обрабатываем обновление настроек голоса
            if message.get("type") == "voice_settings_update":
                new_language = message.get("language")
                new_speed = message.get("speech_speed")
                
                # Детальное логирование запроса
                logger.info(f"🎯 Voice settings update requested:")
                logger.info(f"  📥 Requested language: {new_language}")
                logger.info(f"  📥 Requested speed: {new_speed}")
                logger.info(f"  🔍 Current language: {assistant.voice_settings.language}")
                logger.info(f"  🔍 Current speed: {assistant.voice_settings.speech_speed}")
                
                if new_language or new_speed:
                    # Обновляем настройки через assistant
                    current_language = assistant.voice_settings.language if new_language is None else new_language
                    current_speed = assistant.voice_settings.speech_speed if new_speed is None else new_speed
                    
                    logger.info(f"🔄 Processing voice settings update:")
                    logger.info(f"  🎌 Target language: {current_language}")  
                    logger.info(f"  ⚡ Target speed: {current_speed}")
                    
                    # Запускаем обновление асинхронно
                    async def update_and_confirm():
                        try:
                            await assistant.update_voice_settings(current_language, current_speed)
                            
                            # Отправляем подтверждение обратно на фронтенд
                            confirmation = {
                                "type": "voice_settings_updated",
                                "language": assistant.voice_settings.language,  # Используем актуальные значения
                                "speech_speed": assistant.voice_settings.speech_speed,
                                "status": "success"
                            }
                            await ctx.room.local_participant.publish_data(
                                json.dumps(confirmation).encode('utf-8'),
                                reliable=True,
                                topic="voice_settings_response"
                            )
                            logger.info(f"✅ Voice settings updated and confirmation sent: {confirmation}")
                            
                        except Exception as update_error:
                            logger.error(f"❌ Error updating voice settings: {update_error}")
                            
                            # Отправляем сообщение об ошибке
                            error_response = {
                                "type": "voice_settings_updated",
                                "language": assistant.voice_settings.language,
                                "speech_speed": assistant.voice_settings.speech_speed,
                                "status": "error",
                                "error": str(update_error)
                            }
                            await ctx.room.local_participant.publish_data(
                                json.dumps(error_response).encode('utf-8'),
                                reliable=True,
                                topic="voice_settings_response"
                            )
                    
                    # Запускаем задачу
                    asyncio.create_task(update_and_confirm())
                    
                else:
                    logger.warning("⚠️ Voice settings update request with no language or speed provided")
                    
        except json.JSONDecodeError as json_error:
            logger.error(f"❌ Failed to decode DataChannel JSON message: {json_error}")
            logger.error(f"📄 Raw data: {data.data}")
        except Exception as e:
            logger.error(f"❌ DataChannel message processing error: {e}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")

    # Переменные для отслеживания состояния агента
    assistant.turn_counter = 0

    # Добавляем callback для генерации финального саммари при завершении сессии
    async def on_session_shutdown():
        logger.info("Session ended.")
        await assistant.on_session_end()
    
    ctx.add_shutdown_callback(on_session_shutdown)

    logger.info(f"Starting agent session with language: {assistant.voice_settings.language}")
    logger.info(f"Voice settings: language='{assistant.voice_settings.language}', speed={assistant.voice_settings.speech_speed}")
    
    try:
        await session.start(agent=assistant, room=ctx.room)
        logger.info("✅ Agent session started successfully")
        
        # Генерируем и отправляем приветствие после успешного старта сессии
        try:
            # Получаем приветствие/саммари
            greeting = game_data.latest_summary.summary_text if game_data and game_data.latest_summary else (
                game_data.intro if game_data and game_data.intro else "Добро пожаловать в игру! Опишите ваши действия."
            )
            
            # Если есть latest_summary - это продолжение игры
            if game_data and game_data.latest_summary:
                logger.info(f"📖 Playing latest summary for continuing game: {greeting[:100]}...")
            else:
                logger.info(f"📢 Sending intro greeting for new game: {greeting[:100]}...")
            
            logger.info("🔊 Sending greeting via session.say()")
            await session.say(greeting)
            logger.info("✅ Greeting delivered successfully")
            
        except Exception as greeting_error:
            logger.error(f"❌ Failed to send greeting: {greeting_error}")
        
    except Exception as e:
        logger.error(f"Failed to start agent session: {e}")
        return



if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        shutdown_process_timeout=5,
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm
    ))
