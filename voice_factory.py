"""
Фабрика для создания голосовых компонентов (STT/TTS) для разных языков.
Каждый язык имеет оптимально подобранный провайдер и голос.
"""

import logging
from livekit.plugins import openai, cartesia, deepgram, elevenlabs

logger = logging.getLogger("voice-factory")


class VoiceComponentFactory:
    """Фабрика для создания STT и TTS компонентов для разных языков"""
    
    @staticmethod
    def create_tts(language: str, speed: float = 1.0):
        """
        Создает TTS компонент для указанного языка и скорости
        
        Args:
            language: Код языка (en, ru, nl, fr, es)
            speed: Скорость речи (0.5, 0.75, 1.0, 1.5, 1.75)
            
        Returns:
            TTS компонент соответствующего провайдера
        """
        logger.info(f"Creating TTS for language: {language}, speed: {speed}")
        
        if language == "en":
            return openai.TTS(
                model="tts-1",
                voice="ash",  # Лучший голос для английского
                speed=speed
            )
        elif language == "ru":
            return cartesia.TTS(
                voice="a8a1eb38-5f15-4c1d-8722-7ac0f329727d",  # Русский голос Cartesia
                speed=speed
            )
        elif language == "nl":
            return elevenlabs.TTS(
                voice="dutch_female_voice_id",  # Специальный голландский голос
                speed=speed
            )
        elif language == "fr":
            return openai.TTS(
                model="tts-1",
                voice="nova",  # Лучший для французского
                speed=speed
            )
        elif language == "es":
            return elevenlabs.TTS(
                voice="spanish_male_voice_id",  # Испанский голос
                speed=speed
            )
        else:
            # Fallback на английский
            logger.warning(f"Unknown language {language}, falling back to English")
            return openai.TTS(
                model="tts-1", 
                voice="ash", 
                speed=speed
            )
    
    @staticmethod
    def create_stt(language: str):
        """
        Создает STT компонент для указанного языка
        
        Args:
            language: Код языка (en, ru, nl, fr, es)
            
        Returns:
            STT компонент соответствующего провайдера
        """
        logger.info(f"Creating STT for language: {language}")
        
        if language == "en":
            return openai.STT(language="en")
        elif language == "ru":
            return deepgram.STT(language="ru")
        elif language == "nl":
            return openai.STT(language="nl")
        elif language == "fr":
            return deepgram.STT(language="fr") 
        elif language == "es":
            return openai.STT(language="es")
        else:
            # Fallback на английский
            logger.warning(f"Unknown language {language}, falling back to English")
            return openai.STT(language="en")
    
    @staticmethod
    def get_supported_languages():
        """Возвращает список поддерживаемых языков"""
        return ["en", "ru", "nl", "fr", "es"]
    
    @staticmethod
    def get_supported_speeds():
        """Возвращает список поддерживаемых скоростей речи"""
        return [0.5, 0.75, 1.0, 1.5, 1.75]
    
    @staticmethod
    def validate_settings(language: str, speed: float) -> tuple[str, float]:
        """
        Валидирует и нормализует настройки
        
        Args:
            language: Код языка
            speed: Скорость речи
            
        Returns:
            Tuple с валидными (language, speed)
        """
        # Валидация языка
        if language not in VoiceComponentFactory.get_supported_languages():
            logger.warning(f"Invalid language {language}, using 'en'")
            language = "en"
        
        # Валидация скорости
        supported_speeds = VoiceComponentFactory.get_supported_speeds()
        if speed not in supported_speeds:
            # Находим ближайшую поддерживаемую скорость
            closest_speed = min(supported_speeds, key=lambda x: abs(x - speed))
            logger.warning(f"Invalid speed {speed}, using closest: {closest_speed}")
            speed = closest_speed
        
        return language, speed