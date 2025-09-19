import json
import os
import re
import asyncio
import traceback
import logging
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional

from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaWebPage
import pytz

# --- OCR Imports ---
try:
    from PIL import Image
    import pytesseract
except ImportError:
    print("OCR libraries not found. Please run: pip install pytesseract pillow")
    Image = None
    pytesseract = None
# --------------------

# --- Configuration ---
download_path = 'images/'
TELEGRAM_API_ID = 27992538
TELEGRAM_API_HASH = "1be28adea45cb759f5531a89e7bce84c"
PORT = 8080
api_id = TELEGRAM_API_ID
api_hash = TELEGRAM_API_HASH
session_name = 'session'
config_file = 'config.json'
message_mapping_file = 'message_mapping.json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('bot.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Telegram Bot is running')
    def log_message(self, format, *args):
        pass

def start_health_server():
    try:
        server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
        logger.info(f"Health check server started on port {PORT}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start health server: {e}")

class MessageTracker:
    def __init__(self, tracking_file: str = message_mapping_file):
        self.tracking_file = tracking_file
        self.message_mapping = {}
        self.load_mapping()
        
    def load_mapping(self):
        try:
            if os.path.exists(self.tracking_file):
                with open(self.tracking_file, 'r', encoding='utf-8') as f:
                    self.message_mapping = json.load(f)
        except Exception as e:
            logger.error(f"Error loading message mapping: {e}")
            self.message_mapping = {}
    
    def save_mapping(self):
        try:
            with open(self.tracking_file, 'w', encoding='utf-8') as f:
                json.dump(self.message_mapping, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving message mapping: {e}")
    
    def add_forwarded_message(self, source_chat_id: str, source_msg_id: int, 
                              target_chat_id: str, forwarded_msg_id: int):
        source_chat_id, target_chat_id = str(source_chat_id), str(target_chat_id)
        if source_chat_id not in self.message_mapping:
            self.message_mapping[source_chat_id] = {}
        if str(source_msg_id) not in self.message_mapping[source_chat_id]:
            self.message_mapping[source_chat_id][str(source_msg_id)] = []
        
        self.message_mapping[source_chat_id][str(source_msg_id)].append({
            'target_chat_id': target_chat_id,
            'forwarded_msg_id': forwarded_msg_id,
            'timestamp': datetime.now().isoformat()
        })
        self.save_mapping()
        logger.info(f"Mapped: {source_chat_id}:{source_msg_id} -> {target_chat_id}:{forwarded_msg_id}")
    
    def get_forwarded_messages(self, source_chat_id: str, source_msg_id: int) -> List[Dict]:
        return self.message_mapping.get(str(source_chat_id), {}).get(str(source_msg_id), [])

class TelegramForwarder:
    def __init__(self, api_id: int, api_hash: str, session_name: str, config_file: str):
        self.api_id, self.api_hash, self.session_name, self.config_file = api_id, api_hash, session_name, config_file
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.config: Optional[List[Dict[str, Any]]] = None
        self.target_entities, self.source_to_configs = {}, {}
        self.message_tracker = MessageTracker()
        
    def convert_timezone(self, text: str, source_timezone: str, target_timezone: str) -> str:
        if not all([text, source_timezone, target_timezone]): return text
        try:
            source_tz, target_tz = pytz.timezone(source_timezone), pytz.timezone(target_timezone)
            modified_text = text
            for match in re.finditer(r'\b(\d{1,2}:\d{2})\b', text):
                try:
                    time_obj = datetime.strptime(match.group(0), '%H:%M').time()
                    source_dt = source_tz.localize(datetime.combine(datetime.now(source_tz).date(), time_obj))
                    converted_time = source_dt.astimezone(target_tz).strftime('%H:%M')
                    modified_text = modified_text.replace(match.group(0), converted_time)
                except Exception as e:
                    logger.warning(f"Could not convert time {match.group(0)}: {e}")
            return modified_text
        except Exception as e:
            logger.error(f"Timezone conversion error: {e}"); return text

    def apply_text_replacements(self, text: str, replacements: Dict[str, str]) -> str:
        if not all([text, replacements]): return text
        modified_text = text
        for original, replacement in replacements.items():
            if original in modified_text:
                modified_text = modified_text.replace(original, replacement)
        return modified_text

    def remove_promotional_text(self, text: str, patterns: Optional[List[str]]) -> str:
        if not text: return ""
        user_patterns = patterns or []
        auto_patterns = [
            r'https?://\S+', 
            r'@\w+', 
            r'^\s*(\[?#)',  # --- FIX: This now robustly detects any line starting with '#' or '[#'
            r'^\s*👉\s*\[.*@\w+.*\]'
        ]
        all_patterns, cleaned_lines = user_patterns + auto_patterns, []

        for line in text.split('\n'):
            if not line.strip(): continue
            is_promotional = False
            for pattern in all_patterns:
                try:
                    if re.search(pattern, line, re.IGNORECASE):
                        is_promotional = True
                        logger.info(f"Promotional line removed by pattern '{pattern}': '{line.strip()}'")
                        break
                except re.error:
                     if pattern.lower() in line.lower():
                        is_promotional = True
                        logger.info(f"Promotional line removed by keyword '{pattern}': '{line.strip()}'")
                        break
            if not is_promotional: cleaned_lines.append(line)
        return '\n'.join(cleaned_lines)

    def load_config(self) -> bool:
        try:
            with open(self.config_file, "r", encoding="utf8") as f: self.config = json.load(f)
            self.source_to_configs = {}
            for conf in self.config:
                self.source_to_configs.setdefault(str(conf["source_channel_id"]), []).append(conf)
            return True
        except Exception as e:
            logger.error(f"Failed to load config: {e}"); return False

    async def cache_target_entities(self) -> bool:
        if not self.config: return False
        unique_targets = {c["target_channel_id"] for c in self.config}
        for target_id in unique_targets:
            try:
                self.target_entities[target_id] = await self.client.get_entity(target_id)
            except Exception as e:
                logger.error(f"Could not get entity for target channel {target_id}: {e}")
        logger.info(f"Successfully cached {len(self.target_entities)}/{len(unique_targets)} target entities")
        return bool(self.target_entities)

    async def process_message_for_config(self, message, config: Dict[str, Any]) -> Optional[int]:
        try:
            target_entity = self.target_entities.get(config["target_channel_id"])
            if not target_entity: return None

            full_text = message.text or ""

            if message.photo and config.get("enable_ocr_on_images") and pytesseract:
                image_path = None
                try:
                    logger.info(f"OCR enabled. Downloading image from message {message.id}...")
                    image_path = await message.download_media(file=download_path)
                    ocr_text = await asyncio.to_thread(pytesseract.image_to_string, Image.open(image_path))
                    if ocr_text:
                        logger.info(f"OCR extracted text: {repr(ocr_text[:100])}")
                        full_text += "\n" + ocr_text
                except Exception as e:
                    logger.error(f"OCR processing failed for message {message.id}: {e}")
                finally:
                    if image_path and os.path.exists(image_path):
                        os.remove(image_path)
            
            processed_text = self.remove_promotional_text(full_text, config.get("promotional_patterns"))
            processed_text = self.apply_text_replacements(processed_text, config.get("text_to_replace", {}))
            
            if (src_tz := config.get("source_timezone")) and (tgt_tz := config.get("target_timezone")):
                processed_text = self.convert_timezone(processed_text, src_tz, tgt_tz)
            
            final_text = '\n'.join(line.strip() for line in processed_text.split('\n') if line.strip())
            
            sent_message = None
            is_web_preview = isinstance(message.media, MessageMediaWebPage)

            if final_text or (message.media and config.get("forward_media", True) and not is_web_preview):
                if config.get("forward_caption_only") and message.media and final_text:
                    sent_message = await self.client.send_message(target_entity, final_text)
                
                elif message.photo and not config.get("forward_media", True):
                    if final_text: sent_message = await self.client.send_message(target_entity, final_text)
                
                elif message.media and config.get("forward_media", True) and not is_web_preview:
                    sent_message = await self.client.send_message(target_entity, final_text or "", file=message.media)
                
                elif final_text:
                    sent_message = await self.client.send_message(target_entity, final_text)
            
            return sent_message.id if sent_message else None
        except Exception as e:
            logger.error(f"Error in process_message_for_config: {e}"); traceback.print_exc()
            return None

    async def forward_messages(self, event):
        message, source_id = event.message, str(event.chat_id)
        if not (matching_configs := self.source_to_configs.get(source_id)): return
        
        for config in matching_configs:
            forwarded_msg_id = await self.process_message_for_config(message, config)
            if forwarded_msg_id and config.get("enable_edit_tracking", False):
                self.message_tracker.add_forwarded_message(
                    source_id, message.id, config["target_channel_id"], forwarded_msg_id
                )

    async def handle_message_edits(self, event):
        message, source_id = event.message, str(event.chat_id)
        forwarded_messages = self.message_tracker.get_forwarded_messages(source_id, message.id)
        matching_configs = self.source_to_configs.get(source_id, [])

        for fwd_info in forwarded_messages:
            target_config = next((c for c in matching_configs if str(c["target_channel_id"]) == fwd_info['target_chat_id']), None)
            if not target_config or not target_config.get("enable_edit_tracking", False): continue
            
            target_entity = self.target_entities.get(int(fwd_info['target_chat_id']))
            if not target_entity or not message.text: continue

            processed_text = self.remove_promotional_text(message.text, target_config.get("promotional_patterns"))
            processed_text = self.apply_text_replacements(processed_text, target_config.get("text_to_replace", {}))
            if (src_tz := target_config.get("source_timezone")) and (tgt_tz := target_config.get("target_timezone")):
                processed_text = self.convert_timezone(processed_text, src_tz, tgt_tz)
            
            final_text = '\n'.join(line.strip() for line in processed_text.split('\n') if line.strip())

            if final_text:
                try:
                    await self.client.edit_message(target_entity, fwd_info['forwarded_msg_id'], final_text)
                except Exception as e:
                    logger.error(f"Failed to edit message {fwd_info['forwarded_msg_id']}: {e}")

async def main():
    if not (pytesseract and Image):
        logger.error("OCR dependencies are not installed. Please run 'pip install pytesseract pillow' and install Tesseract engine.")
        return
        
    threading.Thread(target=start_health_server, daemon=True).start()
    forwarder = TelegramForwarder(api_id, api_hash, session_name, config_file)
    
    if not os.path.exists(download_path): os.makedirs(download_path)
    if not forwarder.load_config(): return

    await forwarder.client.start()
    logger.info("Client authentication successful")
    
    if not await forwarder.cache_target_entities():
        logger.warning("No target entities cached, bot may not forward messages.")
    
    source_ids = [int(key) for key in forwarder.source_to_configs.keys()]
    forwarder.client.add_event_handler(forwarder.forward_messages, events.NewMessage(chats=source_ids))
    forwarder.client.add_event_handler(forwarder.handle_message_edits, events.MessageEdited(chats=source_ids))
    
    logger.info("Bot started successfully. Listening for new messages and edits...")
    await forwarder.client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())

