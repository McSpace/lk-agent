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


def create_stt_for_language(language: str):
    """
    Создает Deepgram STT с многоязычной поддержкой nova-3
    Nova-3 использует language=multi для автоматического определения языка
    """
    logger.info(f"🎙️ Creating Deepgram STT with multilingual support for base language: {language}")
    
    return deepgram.STT(
        model="nova-3",
        language="multi",  # Nova-3 использует multilingual режим
        interim_results=True,
        punctuate=True,
        endpointing_ms=100,  # Рекомендуемое значение для multilingual mode
        smart_format=False,
        no_delay=True
    )

def create_cartesia_tts(language: str, speed: float = 1.0):
    """
    Создает Cartesia TTS с подходящими голосами для каждого языка
    Использует модель sonic-2 для всех языков
    """
    # Маппинг языков на ID голосов Cartesia
    voice_mapping = {
        "ru": "da05e96d-ca10-4220-9042-d8acef654fa9",  # Russian voice
        "en": "42b39f37-515f-4eee-8546-73e841679c1d",  # English voice
        "nl": "9e8db62d-056f-47f3-b3b6-1b05767f9176",  # Dutch voice
        "fr": "5c3c89e5-535f-43ef-b14d-f8ffe148c1f0",  # French voice
        "es": "2695b6b5-5543-4be1-96d9-3967fb5e7fec"   # Spanish voice
    }
    
    # Валидация входного языка
    if not language or language not in voice_mapping:
        logger.warning(f"⚠️ Unsupported language '{language}', falling back to English")
        language = "en"
    
    voice_id = voice_mapping[language]
    logger.info(f"🔊 Creating Cartesia TTS for language: {language} -> voice: {voice_id[:8]}...")
    logger.info(f"🎙️ Full voice ID: {voice_id}")
    
    # Валидация voice_id
    if not voice_id or len(voice_id) < 30:  # Cartesia voice IDs обычно длинные UUID
        logger.error(f"❌ Invalid voice_id: {voice_id}")
        raise ValueError(f"Invalid voice_id for language {language}")
    
    try:
        tts_component = cartesia.TTS(
            model="sonic-2",
            language=language,
            voice=voice_id
        )
        logger.info(f"✅ Cartesia TTS component created successfully")
        return tts_component
    except Exception as e:
        logger.error(f"❌ Failed to create Cartesia TTS component: {e}")
        raise


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

async def get_intro_instruction(game_id: str) -> Optional[str]:
    """Получает инструкцию для генерации intro из API"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{os.getenv('STORY_API_URL')}/api/v1/games/{game_id}/intro-instruction"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("instruction")
                logger.error(f"Failed to fetch intro instruction: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Error fetching intro instruction: {e}")
        return None

async def save_intro(game_id: str, intro: str) -> bool:
    """Сохраняет intro, API автоматически генерирует title"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{os.getenv('STORY_API_URL')}/api/v1/games/{game_id}/intro"
            async with session.patch(url, json={"intro": intro}) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ Intro saved, title generated: {data.get('title', 'N/A')}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to save intro: {response.status} - {error_text}")
                    return False
    except Exception as e:
        logger.error(f"Error saving intro: {e}")
        return False

async def send_to_imageGen_api(message_data, turn_id, game_data: GameData):
    """Асинхронная генерация картинки для игровой сцены"""
    try:
        logger.info(f"🌐 send_to_imageGen_api CALLED")
        logger.info(f"  Message data type: {type(message_data)}")
        logger.info(f"  Turn ID: {turn_id}")
        logger.info(f"  Game data: {bool(game_data)}")

        async with aiohttp.ClientSession() as session:
            # Исправляем формат для соответствия API схеме
            payload = {
                "chat_history": message_data.get("content", "") if isinstance(message_data, dict) else str(message_data),
                "illustration_style": game_data.image_style_prompt or "fantasy art style",  # Fallback если None
                "main_character": game_data.character_appearance or "adventurer",  # Fallback если None
                "file_name": turn_id  # Используем turn_id как file_name
            }

            logger.info(f"🌐 HTTP REQUEST to StoryImageGen")
            logger.info(f"  Method: POST")
            logger.info(f"  URL: https://storyimagegen-production.up.railway.app/process_chat")
            logger.info(f"  Timeout: 60s")
            logger.info(f"  Payload: {payload}")
            logger.info(f"  Payload size: {len(str(payload))} chars")

            async with session.post("https://storyimagegen-production.up.railway.app/process_chat",
                                    timeout=60,
                                    json=payload) as response:
                logger.info(f"📥 HTTP RESPONSE received")
                logger.info(f"  Status: {response.status}")

                if response.status == 200:
                    result = await response.json()
                    logger.info(f"  Response size: {len(str(result))} chars")
                    logger.info("✅ Image generation completed successfully")
                    logger.info(f"  Result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
                    return result
                else:
                    error_text = await response.text()
                    logger.info(f"  Error response size: {len(error_text)} chars")
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
            logger.info(f"[AGENT DEBUG] Calling summary API: {url}")
            async with session.post(url) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"[AGENT DEBUG] Summary API response: {result}")
                    logger.info(f"✅ Summary generated for game {game_id}: turn {result.get('turn_number', 'unknown')}")
                    
                    # Log the actual summary content for debugging
                    summary_text = result.get('summary_text', 'No summary text found')
                    logger.info(f"[AGENT DEBUG] Generated summary content: '{summary_text[:100]}...'")
                    return True
                else:
                    response_text = await response.text()
                    logger.error(f"❌ Summary generation failed: {response.status}, body: {response_text}")
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
        You are a text-based RPG game master. Write all responses in {user_lang}.
        The player describes their actions, and you describe how the world reacts.
        Keep your responses brief but engaging, always in {user_lang}.
        
        You have access to game tools:
        - roll_dice: for dice rolls during checks
        - check_inventory: to check player's inventory
        
        Use these tools when the player attempts actions that require checks.

        Game World:
        {game_data.world_description if game_data else 'Medieval fantasy world'}

        Character:
        {game_data.character_description if game_data else 'Unknown hero'}

        {f'Current state: {game_data.latest_summary.summary_text}' if game_data and game_data.latest_summary else ''}
        """
        
        super().__init__(instructions=instructions.strip())
        self.game_data = game_data
        self.ctx = ctx
        self.turn_counter = 0  # Счетчик ходов для автоматической генерации саммари
        self.pending_user_message = None  # Хранение пользовательского сообщения для раннего сохранения
        self.early_save_triggered = False  # Флаг для предотвращения дублирования сохранений
        
        # Настройки голоса пользователя
        self.voice_settings = user_settings
        
        # Инициализируем текущие STT и TTS компоненты
        self.current_stt = create_stt_for_language(self.voice_settings.language)
        self.current_tts = create_cartesia_tts(
            self.voice_settings.language, 
            self.voice_settings.speech_speed
        )
        
        # Инициализируем fallback для updated_instructions
        self.updated_instructions = None
        
        # Обновление инструкций будет выполнено в on_enter() так как это async операция
        
        logger.info(f"🎛️ Voice settings initialized: language='{self.voice_settings.language}', speed={self.voice_settings.speech_speed}")
        logger.info(f"🎙️ Initial STT component created for language: {self.voice_settings.language}")
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
        """Обновляет LLM инструкции с текущим языком используя update_chat_ctx для модификации существующего контекста"""
        try:
            user_lang = self._get_language_name(self.voice_settings.language)
            
            # Пересоздаем инструкции с обновленным языком
            updated_instructions = f"""
            You are a text-based RPG game master. Write all responses in {user_lang}.
            The player describes their actions, and you describe how the world reacts.
            Keep your responses brief but engaging, always in {user_lang}.
            
            You have access to game tools:
            - roll_dice: for dice rolls during checks
            - check_inventory: to check player's inventory
            
            Use these tools when the player attempts actions that require checks.

            Game World:
            {self.game_data.world_description if self.game_data else 'Medieval fantasy world'}

            Character:
            {self.game_data.character_description if self.game_data else 'Unknown hero'}

            {f'Current state: {self.game_data.latest_summary.summary_text}' if self.game_data and self.game_data.latest_summary else ''}
            """.strip()
            
            logger.info(f"🔄 Updating instructions for language switch to: {user_lang}")
            
            # Используем только update_instructions() - возможно он все-таки работает правильно
            await self.update_instructions(updated_instructions)
            logger.info(f"✅ Instructions updated via update_instructions() for language: {user_lang}")
            
            # Пока отключаем сложную логику с chat context из-за ReadOnlyChatContext проблем
            # TODO: Исследовать правильный способ работы с ReadOnlyChatContext в LiveKit 1.x
            logger.info(f"📝 Using simplified approach with update_instructions() only")
            
        except Exception as e:
            logger.error(f"❌ Failed to update chat context: {e}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            
            # Fallback - сохраняем инструкции для ручной обработки в llm_node
            self.updated_instructions = updated_instructions
            logger.info(f"🔄 Fallback: storing instructions for manual llm_node processing")

    async def recreate_stt_component(self):
        """Пересоздает STT компонент с новыми настройками языка"""
        try:
            logger.info(f"🎙️ Recreating STT component for language: {self.voice_settings.language}")
            
            # Создаем новый STT компонент с правильным языком
            new_stt = create_stt_for_language(self.voice_settings.language)
            
            # Сохраняем ссылку для возможного использования
            self.current_stt = new_stt
            logger.info(f"🎯 New STT component created and stored")
            
            return new_stt
            
        except Exception as e:
            logger.error(f"❌ Failed to recreate STT component: {e}")
            return None

    async def recreate_tts_component(self):
        """Пересоздает TTS компонент с новыми настройками языка"""
        try:
            old_voice_id = None
            if hasattr(self, 'current_tts') and self.current_tts and hasattr(self.current_tts, 'voice'):
                old_voice_id = self.current_tts.voice
            
            logger.info(f"🔊 Recreating TTS component for language: {self.voice_settings.language}")
            logger.info(f"🔄 Previous voice ID: {old_voice_id[:8] + '...' if old_voice_id else 'None'}")
            
            # Создаем новый Cartesia TTS компонент
            new_tts = create_cartesia_tts(
                self.voice_settings.language, 
                self.voice_settings.speech_speed
            )
            
            # Логируем информацию о новом компоненте
            if hasattr(new_tts, 'voice'):
                new_voice_id = new_tts.voice
                logger.info(f"🎯 New TTS component created with voice ID: {new_voice_id[:8]}...")
                logger.info(f"🔄 Voice changed: {old_voice_id != new_voice_id}")
            else:
                logger.warning("⚠️ New TTS component doesn't have voice attribute")
            
            # Сохраняем ссылку для использования в tts_node
            self.current_tts = new_tts
            logger.info(f"✅ New TTS component stored successfully")
            
            return new_tts
            
        except Exception as e:
            logger.error(f"❌ Failed to recreate TTS component: {e}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
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
        
        # Если язык изменился, обновляем LLM инструкции
        if old_language != validated_language:
            logger.info(f"🌐 Language changed from {old_language} to {validated_language}")
            await self.update_llm_instructions()
            
            # Попытка обновить TTS компонент в AgentSession напрямую
            if hasattr(self, '_agent_session') and self._agent_session:
                try:
                    logger.info(f"🔄 Attempting to update TTS in AgentSession")
                    new_tts = create_cartesia_tts(validated_language, validated_speed)
                    
                    # Попробуем обновить TTS в сессии напрямую
                    if hasattr(self._agent_session, '_tts'):
                        old_tts_type = type(self._agent_session._tts).__name__ if self._agent_session._tts else "None"
                        self._agent_session._tts = new_tts
                        logger.info(f"✅ AgentSession TTS updated from {old_tts_type} to {type(new_tts).__name__}")
                    else:
                        logger.warning("⚠️ AgentSession doesn't have _tts attribute")
                        
                except Exception as e:
                    logger.error(f"❌ Failed to update TTS in AgentSession: {e}")
            else:
                logger.warning("⚠️ No AgentSession reference available for TTS update")
            
            logger.info(f"📝 STT remains multilingual, no recreation needed")
        
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

    # ВРЕМЕННО ОТКЛЮЧЕНО: переопределение tts_node() вызывает проблемы с async_generator
    # Cartesia TTS не может сериализовать async_generator в JSON
    # Нужно найти другой способ обновлять TTS компоненты в runtime
    #
    # async def tts_node(self, text, model_settings):
    #     """Переопределенный tts_node для использования динамически созданного TTS компонента"""
    #     logger.info(f"🔊 tts_node called with language='{self.voice_settings.language}', speed={self.voice_settings.speech_speed}")
    #     logger.info(f"🔍 Text input type: {type(text)}, model_settings: {model_settings}")
    #     
    #     try:
    #         # Используем текущий TTS компонент (обновляется в recreate_tts_component)
    #         if hasattr(self, 'current_tts') and self.current_tts:
    #             logger.info(f"🎯 Using current TTS component: {type(self.current_tts).__name__}")
    #             
    #             # Получаем информацию о текущем голосе для Cartesia TTS
    #             if hasattr(self.current_tts, 'voice'):
    #                 voice_id = self.current_tts.voice
    #                 logger.info(f"🎙️ Using voice ID: {voice_id[:8]}... for language: {self.voice_settings.language}")
    #             else:
    #                 logger.info(f"🎙️ TTS component voice info not available")
    #             
    #             # Правильно вызываем synthesize - передаем text stream
    #             synthesis_stream = self.current_tts.synthesize(text)
    #             logger.info(f"🔄 Got synthesis stream: {type(synthesis_stream)}")
    #             
    #             frame_count = 0
    #             async for frame in synthesis_stream:
    #                 frame_count += 1
    #                 yield frame
    #                 
    #             logger.info(f"✅ TTS synthesis completed successfully ({frame_count} frames)")
    #         else:
    #             logger.warning("⚠️ No current TTS component, falling back to default")
    #             # Fallback на дефолтный TTS
    #             async for frame in super().tts_node(text, model_settings):
    #                 yield frame
    #             
    #     except Exception as e:
    #         logger.error(f"❌ TTS node error: {e}")
    #         logger.error(f"📍 Error details: {type(e).__name__}: {str(e)}")
    #         import traceback
    #         logger.error(f"🔍 Traceback: {traceback.format_exc()}")
    #         
    #         # Fallback на дефолтный TTS
    #         logger.info("🔄 Falling back to default TTS")
    #         try:
    #             async for frame in super().tts_node(text, model_settings):
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
            
            # Добавляем логирование текущих инструкций для отладки
            if hasattr(self.llm, '_instructions'):
                logger.info(f"[AGENT DEBUG] Current LLM instructions: {self.llm._instructions[:200]}...")
            else:
                logger.info(f"[AGENT DEBUG] Unable to read current LLM instructions")
            
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
                        logger.info("🎯 CHUNK WITH USAGE DETECTED - MARKING AS LAST CHUNK")
                        logger.info(f"📊 Usage details: {chunk.usage}")
                        is_last_chunk = True
                    else:
                        logger.debug(f"📦 Regular chunk #{chunk_count} without usage")
                else:
                    # Для строковых чанков (простые LLM ответы)
                    current_response_chunks.append(str(chunk))
                    is_last_chunk = True
                    #logger.info(f"🎯 String chunk received - treating as last: '{str(chunk)[:50]}...'")
            
            logger.info(f"✅ Chunk iteration completed. Total chunks: {chunk_count}")
            
            # Получаем полный ответ этого вызова
            full_response = ''.join(current_response_chunks)
            logger.info(f"📝 llm_node completed - response: '{full_response[:100]}...' (length: {len(full_response)})")
            
            # Проверяем это новая игра (intro generation) или обычный ход
            is_new_game_intro = (not self.pending_user_message and
                                 self.game_data and
                                 (not self.game_data.intro or self.game_data.intro == ""))

            # Детальное логирование каждого условия для диагностики
            logger.info(f"🔍 DETAILED Save conditions check:")
            logger.info(f"  is_last_chunk: {is_last_chunk} (required: True)")
            logger.info(f"  pending_user_message exists: {bool(self.pending_user_message)}")
            logger.info(f"  pending_user_message content: '{self.pending_user_message[:50] if self.pending_user_message else 'None'}...'")
            logger.info(f"  early_save_triggered: {self.early_save_triggered} (required: False)")
            logger.info(f"  is_new_game_intro: {is_new_game_intro}")

            # Если это последний чанк и либо обычный ход либо intro новой игры - сохраняем
            if is_last_chunk and not self.early_save_triggered:
                if self.pending_user_message:
                    # Обычный ход игры
                    logger.info("✅ NORMAL TURN - TRIGGERING SAVE AND IMAGE GENERATION")
                    self.early_save_triggered = True
                    logger.info(f"📄 Full agent response: {full_response}")
                    logger.info("⚡ Immediate save triggered - calling _save_turn_immediately")

                    import asyncio
                    asyncio.create_task(self._save_turn_immediately(self.pending_user_message, full_response))
                    self.pending_user_message = None

                elif is_new_game_intro:
                    # Intro для новой игры
                    logger.info("✅ NEW GAME INTRO - TRIGGERING SAVE AND IMAGE GENERATION")
                    self.early_save_triggered = True
                    logger.info(f"📄 Generated intro: {full_response[:100]}...")

                    import asyncio
                    # Сохраняем intro (title сгенерируется автоматически в API)
                    asyncio.create_task(save_intro(str(self.game_data.game.id), full_response))

                    # Генерируем изображение для intro
                    asyncio.create_task(self._save_turn_immediately("START_OF_GAME", full_response))

                else:
                    logger.warning("❌ CONDITIONS NOT MET - NO SAVE/IMAGE GENERATION")
            else:
                logger.warning("❌ CONDITIONS NOT MET - NO IMAGE GENERATION")
                if not is_last_chunk:
                    logger.warning("  → Missing: is_last_chunk=False")
                if self.early_save_triggered:
                    logger.warning("  → Blocked: early_save_triggered=True")
                if not self.pending_user_message and not is_new_game_intro:
                    logger.warning("  → Missing: neither user message nor new game intro")

            # Сводное логирование состояния для диагностики
            logger.info(f"📋 LLM_NODE SUMMARY:")
            logger.info(f"  Total chunks processed: {chunk_count}")
            logger.info(f"  Final is_last_chunk: {is_last_chunk}")
            logger.info(f"  Response length: {len(full_response)}")
            logger.info(f"  Image generation triggered: {is_last_chunk and self.pending_user_message and not self.early_save_triggered}")

        except Exception as e:
            logger.error(f"❌ Exception in llm_node: {e}")
            logger.error(f"📍 Exception details: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            raise


    async def on_user_turn_completed(self, turn_ctx, new_message):
        """Вызывается когда пользователь закончил говорить, до ответа агента"""
        logger.info(f"🎤 USER TURN COMPLETED - STORING MESSAGE")
        logger.info(f"  Raw message type: {type(new_message.content)}")
        logger.info(f"  Raw message content: {new_message.content}")

        # Извлекаем пользовательское сообщение
        user_content = new_message.content
        if isinstance(user_content, list) and len(user_content) > 0:
            user_content = user_content[0]
            logger.info(f"  Extracted from list[0]: '{user_content}'")
        elif isinstance(user_content, list):
            user_content = ""
            logger.info(f"  Empty list - using empty string")
        else:
            logger.info(f"  Direct content: '{user_content}'")

        # Сохраняем для использования в llm_node
        processed_content = str(user_content)
        self.pending_user_message = processed_content
        self.early_save_triggered = False  # Сбрасываем флаг для нового хода

        logger.info(f"💬 User message processed and stored:")
        logger.info(f"  Processed content: '{processed_content[:100]}...'")
        logger.info(f"  early_save_triggered reset to: False")
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
        logger.info(f"🎨 handle_imagegen_api STARTED")
        logger.info(f"  GM text type: {type(gm_text)}")
        logger.info(f"  GM text preview: '{str(gm_text)[:100]}...'")
        logger.info(f"  Turn ID: {last_turn_id}")
        logger.info(f"  User text: '{user_text[:50]}...'")
        logger.info(f"  Game data available: {bool(self.game_data)}")

        image_url = ""
        image_prompt = ""

        try:
            # Конвертируем сообщение в правильный формат для API
            if isinstance(gm_text, list):
                gm_text = gm_text[0] if len(gm_text) > 0 else ""
            gm_text = str(gm_text)
            
            # Создаем простую структуру для API (не объект ChatMessage)
            chat_history_for_api = {"content": gm_text}
            logger.info(f"🌐 CALLING StoryImageGen API")
            logger.info(f"  API payload structure: {chat_history_for_api}")
            logger.info(f"  Game data for API: illustration_style='{self.game_data.image_style_prompt if self.game_data else 'None'}'")
            logger.info(f"  Game data for API: character_appearance='{self.game_data.character_appearance if self.game_data else 'None'}'")

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
            logger.info(f"🎨 _save_and_generate_image CALLED")
            logger.info(f"  User message type: {type(user_message)}")
            logger.info(f"  Agent message type: {type(agent_message)}")
            logger.info(f"  Game data available: {bool(self.game_data)}")

            # Исправляем формат сообщений - конвертируем массивы в строки
            if isinstance(agent_message, list):
                agent_message = agent_message[0] if len(agent_message) > 0 else ""
                logger.info(f"  Agent message extracted from list: '{agent_message[:50]}...'")
            if isinstance(user_message, list):
                user_message = user_message[0] if len(user_message) > 0 else ""
                logger.info(f"  User message extracted from list: '{user_message[:50]}...'")

            # Убеждаемся что это строки
            agent_message = str(agent_message)
            user_message = str(user_message)

            logger.info(f"💾 Final processed messages:")
            logger.info(f"  User: '{user_message[:50]}...' (length: {len(user_message)})")
            logger.info(f"  Agent: '{agent_message[:50]}...' (length: {len(agent_message)})")

            # НЕ сохраняем ход сразу - ждем генерации картинки
            # import asyncio
            # asyncio.create_task(self.save_turn_background(user_message, agent_message))
            # logger.info("📊 Turn saved successfully")

            # Генерируем картинку на каждом ходе - сохранение произойдет там
            import uuid
            turn_id = str(uuid.uuid4())
            logger.info("🎨 LAUNCHING handle_imagegen_api TASK")
            logger.info(f"  Turn ID: {turn_id}")
            logger.info(f"  Will call: handle_imagegen_api(agent_message, turn_id, user_msg)")

            # Используем сохраненное пользовательское сообщение
            user_msg = getattr(self, 'last_user_message', user_message)
            logger.info(f"  Using user_msg: '{user_msg[:50]}...'")

            import asyncio
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
            stt=create_stt_for_language(user_voice_settings.language),
            llm=openai.LLM(model="gpt-4o"),  # Используем более мощную модель для RPG агента
            tts=create_cartesia_tts(
                user_voice_settings.language, 
                user_voice_settings.speech_speed
            ),
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
                            # Сохраняем старый язык для проверки изменений
                            old_language = assistant.voice_settings.language
                            
                            await assistant.update_voice_settings(current_language, current_speed)
                            
                            # Сохраняем новый язык в базу данных через API если он изменился
                            if assistant.game_data and new_language and old_language != assistant.voice_settings.language:
                                try:
                                    user_id = str(assistant.game_data.game.user_id)
                                    async with aiohttp.ClientSession() as session:
                                        update_data = {"language_code": assistant.voice_settings.language}
                                        async with session.put(
                                            f"{os.getenv('STORY_API_URL')}/api/v1/users/{user_id}",
                                            json=update_data
                                        ) as response:
                                            if response.status == 200:
                                                logger.info(f"✅ User language updated in database: {assistant.voice_settings.language}")
                                            else:
                                                error_text = await response.text()
                                                logger.warning(f"⚠️ Failed to update user language in database: {response.status} - {error_text}")
                                except Exception as db_error:
                                    logger.error(f"❌ Error updating user language in database: {db_error}")
                            
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
    
    # Сохраняем ссылку на сессию в assistant для обновления TTS компонентов
    assistant._agent_session = session

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
            # Проверяем это новая игра или продолжение
            if game_data and (not game_data.intro or game_data.intro == ""):
                # Новая игра - генерируем intro потоково через LLM
                logger.info("🆕 New game detected - generating intro via LLM streaming")

                # Получаем инструкцию для генерации intro
                intro_instruction = await get_intro_instruction(game_id)
                if not intro_instruction:
                    logger.error("❌ Failed to get intro instruction, using fallback")
                    await session.say("Welcome to the game!")
                else:
                    logger.info(f"📝 Received intro instruction, starting streaming generation")

                    # Генерируем intro потоково через session.generate_reply
                    # Сохранение intro и генерация изображения произойдут в llm_node
                    speech_handle = await session.generate_reply(
                        instructions=intro_instruction,
                        allow_interruptions=True
                    )

                    logger.info("🎙️ Intro streaming started")

                    # Ждем завершения озвучки (правильный API LiveKit 1.x - join() возвращает asyncio.Future)
                    await speech_handle.join()

                    logger.info(f"✅ Intro generation and playout completed")
                    logger.info(f"💾 Intro text saved and image generated by llm_node")

            elif game_data and game_data.latest_summary:
                # Продолжение игры - озвучиваем саммари
                logger.info(f"📖 Continuing game - playing summary")
                await session.say(game_data.latest_summary.summary_text)
                logger.info("✅ Summary delivered successfully")

            elif game_data and game_data.intro:
                # Старая игра с готовым intro
                logger.info(f"📢 Existing game - playing intro")
                await session.say(game_data.intro)
                logger.info("✅ Intro delivered successfully")

            else:
                # Fallback
                logger.warning("⚠️ No game data available, using default greeting")
                await session.say("Welcome to the game!")

        except Exception as greeting_error:
            logger.error(f"❌ Failed to send greeting: {greeting_error}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
        
    except Exception as e:
        logger.error(f"Failed to start agent session: {e}")
        return



if __name__ == "__main__":
    import sys

    # Handle download-files command for Docker build
    if len(sys.argv) > 1 and sys.argv[1] == "download-files":
        logger.info("📥 Downloading required models for offline usage...")

        # Download Silero VAD models
        try:
            logger.info("⏬ Downloading Silero VAD models...")
            _ = silero.VAD.load()
            logger.info("✅ Silero VAD models downloaded")
        except Exception as e:
            logger.error(f"❌ Failed to download Silero VAD: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Download multilingual turn detector models using plugin API
        try:
            logger.info("⏬ Downloading multilingual turn detector models...")
            from livekit.plugins import turn_detector
            from livekit.agents import Plugin

            # Get the registered plugins (it's a list property, not a method)
            plugins = Plugin.registered_plugins
            logger.info(f"Found {len(plugins)} registered plugins")

            for plugin in plugins:
                logger.info(f"Checking plugin: {plugin.package}")
                if 'turn_detector' in plugin.package:
                    logger.info(f"Found turn detector plugin: {plugin.package}")
                    plugin.download_files()
                    logger.info("✅ Multilingual turn detector models downloaded")
                    break
            else:
                logger.warning("⚠️ Turn detector plugin not found in registered plugins")

        except Exception as e:
            logger.error(f"❌ Failed to download turn detector: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Download Deepgram and Cartesia models (they don't need pre-download, API-based)
        logger.info("ℹ️ Deepgram and Cartesia are API-based, no pre-download needed")

        logger.info("✅ All models downloaded successfully!")
        sys.exit(0)

    # Normal agent startup
    cli.run_app(WorkerOptions(
        shutdown_process_timeout=5,
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm
    ))
