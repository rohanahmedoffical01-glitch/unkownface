import json
import os
import re
import asyncio
import traceback
import unicodedata
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Set

from http.server import HTTPServer, BaseHTTPRequestHandler

from telethon import TelegramClient, events
from telethon.tl.types import PeerUser, PeerChat, PeerChannel
import pytz

# --- Configuration ---
# Path to save downloaded images temporarily
download_path = 'images/'

# Your Telegram API credentials
# --- YOUR CREDENTIALS HAVE BEEN ADDED HERE ---
TELEGRAM_API_ID = 27992538
TELEGRAM_API_HASH = "1be28adea45cb759f5531a89e7bce84c"
# ---------------------------------------------
PORT = 8080

api_id = TELEGRAM_API_ID
api_hash = TELEGRAM_API_HASH
# The name of the session file
session_name = 'session'
# The name of the configuration file
config_file = 'config.json'
# Message mapping file for edit tracking
message_mapping_file = 'message_mapping.json'

# Set up logging with improved formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HealthHandler(BaseHTTPRequestHandler):
    """Simple health check handler for Render deployment"""
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Telegram Bot is running')
    
    def log_message(self, format, *args):
        # Suppress health check logs
        pass

def start_health_server():
    """Start health check server for Render deployment"""
    try:
        port = PORT
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        logger.info(f"Health check server started on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start health server: {e}")

class MessageTracker:
    """
    Tracks mapping between source messages and forwarded messages for edit handling
    """
    
    def __init__(self, tracking_file: str = message_mapping_file):
        self.tracking_file = tracking_file
        self.message_mapping = {}  # source_chat_id -> {source_msg_id: [forwarded_msg_info]}
        self.load_mapping()
        
    def load_mapping(self):
        """Load message mapping from file"""
        try:
            if os.path.exists(self.tracking_file):
                with open(self.tracking_file, 'r', encoding='utf-8') as f:
                    self.message_mapping = json.load(f)
                logger.info(f"Loaded message mapping: {len(self.message_mapping)} source chats")
            else:
                self.message_mapping = {}
                logger.info("No existing message mapping found")
        except Exception as e:
            logger.error(f"Error loading message mapping: {e}")
            self.message_mapping = {}
    
    def save_mapping(self):
        """Save message mapping to file"""
        try:
            with open(self.tracking_file, 'w', encoding='utf-8') as f:
                json.dump(self.message_mapping, f, indent=2, ensure_ascii=False)
            logger.debug("Message mapping saved successfully")
        except Exception as e:
            logger.error(f"Error saving message mapping: {e}")
    
    def add_forwarded_message(self, source_chat_id: str, source_msg_id: int, 
                            target_chat_id: str, forwarded_msg_id: int):
        """Add a mapping between source message and forwarded message"""
        source_chat_id = str(source_chat_id)
        target_chat_id = str(target_chat_id)
        
        if source_chat_id not in self.message_mapping:
            self.message_mapping[source_chat_id] = {}
        
        if str(source_msg_id) not in self.message_mapping[source_chat_id]:
            self.message_mapping[source_chat_id][str(source_msg_id)] = []
        
        forwarded_info = {
            'target_chat_id': target_chat_id,
            'forwarded_msg_id': forwarded_msg_id,
            'timestamp': datetime.now().isoformat()
        }
        
        self.message_mapping[source_chat_id][str(source_msg_id)].append(forwarded_info)
        self.save_mapping()
        
        logger.info(f"Mapped: {source_chat_id}:{source_msg_id} -> {target_chat_id}:{forwarded_msg_id}")
    
    def get_forwarded_messages(self, source_chat_id: str, source_msg_id: int) -> List[Dict]:
        """Get all forwarded messages for a source message"""
        source_chat_id = str(source_chat_id)
        source_msg_id = str(source_msg_id)
        
        return self.message_mapping.get(source_chat_id, {}).get(source_msg_id, [])
    
    def cleanup_old_mappings(self, days: int = 7):
        """Remove mappings older than specified days"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        for source_chat_id in list(self.message_mapping.keys()):
            for source_msg_id in list(self.message_mapping[source_chat_id].keys()):
                forwarded_messages = self.message_mapping[source_chat_id][source_msg_id]
                
                # Filter out old messages
                recent_messages = []
                for msg_info in forwarded_messages:
                    try:
                        msg_date = datetime.fromisoformat(msg_info['timestamp'])
                        if msg_date > cutoff_date:
                            recent_messages.append(msg_info)
                    except:
                        # Keep if can't parse date (safety)
                        recent_messages.append(msg_info)
                
                if recent_messages:
                    self.message_mapping[source_chat_id][source_msg_id] = recent_messages
                else:
                    del self.message_mapping[source_chat_id][source_msg_id]
            
            # Remove empty source chats
            if not self.message_mapping[source_chat_id]:
                del self.message_mapping[source_chat_id]
        
        self.save_mapping()
        logger.info(f"Cleaned up message mappings older than {days} days")

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

    def load_config(self) -> bool:
        try:
            with open(self.config_file, "r", encoding="utf8") as f: self.config = json.load(f)
            self.source_to_configs = {}
            for conf in self.config:
                self.source_to_configs.setdefault(str(conf["source_channel_id"]), []).append(conf)
            logger.info(f"Loaded configuration for {len(self.config)} channel mappings")
            return True
        except Exception as e:
            logger.error(f"Failed to load config: {e}"); return False

    async def cache_target_entities(self) -> bool:
        if not self.config: return False
        self.target_entities.clear()
        unique_targets = {c["target_channel_id"] for c in self.config}
        cached_entities = await asyncio.gather(
            *(self.client.get_entity(target_id) for target_id in unique_targets),
            return_exceptions=True
        )
        for target_id, entity in zip(unique_targets, cached_entities):
            if not isinstance(entity, Exception):
                self.target_entities[target_id] = entity
            else:
                logger.error(f"Could not get entity for target channel {target_id}: {entity}")
        logger.info(f"Successfully cached {len(self.target_entities)}/{len(unique_targets)} target entities")
        return bool(self.target_entities)

    async def process_message_for_config(self, message, config: Dict[str, Any]) -> Optional[int]:
        """
        Processes a message for a specific configuration and returns the forwarded message ID.
        """
        try:
            if not (target_entity := self.target_entities.get(config["target_channel_id"])): return None

            # Debug: Log the incoming message text
            if message.text:
                logger.info(f"Message received: {repr(message.text[:200])}")
            
            # Filter: Only forward Signal Bot, Signal Result, and Currency Statistics messages
            if message.text:
                signal_keywords = [
                    "Signal Bot", "🤖", "💰", "Signal Result", 
                    "Bot [2 Gales]", "CALL", "PUT", "🟢", "🔴", "🎯",
                    "💱", "Currency statistics"
                ]
                is_signal_message = any(keyword in message.text for keyword in signal_keywords)
                if not is_signal_message:
                    logger.info(f"Message filtered out - no signal keywords found")
                    return None
                else:
                    logger.info(f"Signal message detected and will be forwarded")

            forward_text = None
            if message.text:
                processed_text = message.text
                
                # Remove unwanted text first
                for remove_text in config.get("text_to_remove", []):
                    processed_text = processed_text.replace(remove_text, "")
                
                # Apply text replacements
                processed_text = self.apply_text_replacements(processed_text, config.get("text_to_replace", {}))
                
                # Apply timezone conversion if configured
                if (src_tz := config.get("source_timezone")) and (tgt_tz := config.get("target_timezone")):
                    processed_text = self.convert_timezone(processed_text, src_tz, tgt_tz)
                
                # Clean up extra whitespace and empty lines
                processed_text = '\n'.join(line.strip() for line in processed_text.split('\n') if line.strip())
                
                forward_text = processed_text

            sent_message = None

            if config.get("forward_caption_only") and message.media and forward_text:
                sent_message = await self.client.send_message(target_entity, forward_text)
            elif message.media and config.get("forward_media", True):
                # Check if it's a sticker and if stickers are disabled
                if hasattr(message.media, 'document') and any(hasattr(a, 'stickerset') for a in getattr(message.media.document, 'attributes', [])):
                    if not config.get("forward_stickers", True): return None
                
                # Handle different media types
                from telethon.tl.types import MessageMediaWebPage
                if isinstance(message.media, MessageMediaWebPage):
                    # Web page previews should be sent as text with the URL
                    sent_message = await self.client.send_message(target_entity, forward_text or "")
                else:
                    # For other media types (photos, documents, etc.)
                    sent_message = await self.client.send_message(target_entity, forward_text or "", file=message.media)
            elif forward_text:
                sent_message = await self.client.send_message(target_entity, forward_text)
            
            return sent_message.id if sent_message else None
            
        except Exception as e:
            logger.error(f"Error in process_message_for_config: {e}")
            return None

    async def forward_messages(self, event):
        """
        Forwards new messages and tracks them if edit tracking is enabled.
        """
        message, source_id = event.message, str(event.chat_id)
        try:
            if not (matching_configs := self.source_to_configs.get(source_id)): return
            
            logger.info(f"Processing message from {source_id} for {len(matching_configs)} target(s)")
            
            successful_forwards = 0
            for config in matching_configs:
                forwarded_msg_id = await self.process_message_for_config(message, config)
                
                if forwarded_msg_id:
                    successful_forwards += 1
                    
                    if config.get("enable_edit_tracking", False):
                        self.message_tracker.add_forwarded_message(
                            source_chat_id=source_id,
                            source_msg_id=message.id,
                            target_chat_id=config["target_channel_id"],
                            forwarded_msg_id=forwarded_msg_id
                        )
                        logger.info(f"Edit tracking enabled: mapped {source_id}:{message.id} -> {config['target_channel_id']}:{forwarded_msg_id}")
            
            logger.info(f"Successfully forwarded to {successful_forwards}/{len(matching_configs)} targets")

        except Exception as e:
            logger.error(f"An error occurred in forward_messages: {e}"); traceback.print_exc()

    async def handle_message_edits(self, event):
        """
        Handles message edits from source channels if edit tracking is enabled.
        """
        message, source_id = event.message, str(event.chat_id)
        
        try:
            logger.info(f"Message edit detected from {source_id}, message ID: {message.id}")
            
            forwarded_messages = self.message_tracker.get_forwarded_messages(source_id, message.id)
            
            if not forwarded_messages:
                logger.info(f"No forwarded messages found for edited message {source_id}:{message.id} (edit tracking may not be enabled)")
                return
            
            matching_configs = self.source_to_configs.get(source_id, [])
            if not matching_configs:
                return
            
            successful_edits = 0
            for forwarded_info in forwarded_messages:
                target_chat_id = forwarded_info['target_chat_id']
                forwarded_msg_id = forwarded_info['forwarded_msg_id']
                
                target_config = next((c for c in matching_configs if str(c["target_channel_id"]) == target_chat_id), None)
                
                if not target_config or not target_config.get("enable_edit_tracking", False):
                    logger.info(f"Edit tracking disabled or config not found for {target_chat_id}, skipping edit")
                    continue
                
                if not (target_entity := self.target_entities.get(target_config["target_channel_id"])):
                    continue
                
                try:
                    edited_text = None
                    if message.text:
                        processed_text = self.apply_text_replacements(
                            message.text, 
                            target_config.get("text_to_replace", {})
                        )
                        if (src_tz := target_config.get("source_timezone")) and (tgt_tz := target_config.get("target_timezone")):
                            processed_text = self.convert_timezone(processed_text, src_tz, tgt_tz)
                        edited_text = processed_text
                    
                    if edited_text is not None:
                        await self.client.edit_message(target_entity, forwarded_msg_id, edited_text)
                        successful_edits += 1
                        logger.info(f"Successfully edited message {target_chat_id}:{forwarded_msg_id}")
                    else:
                        logger.warning(f"Edited message {source_id}:{message.id} resulted in empty text, not editing.")

                except Exception as e:
                    logger.error(f"Failed to edit message {target_chat_id}:{forwarded_msg_id}: {e}")
            
            logger.info(f"Successfully edited {successful_edits}/{len(forwarded_messages)} forwarded messages")
            
        except Exception as e:
            logger.error(f"An error occurred in handle_message_edits: {e}")
            traceback.print_exc()

    async def message_mapping_cleanup_scheduler(self):
        """
        Cleans up old message mappings periodically.
        """
        while True:
            try:
                await asyncio.sleep(24 * 60 * 60)  # 24 hours
                self.message_tracker.cleanup_old_mappings(days=7)
                logger.info("Completed periodic message mapping cleanup")
            except Exception as e:
                logger.error(f"Error in message mapping cleanup: {e}")

async def main():
    try:
        threading.Thread(target=start_health_server, daemon=True).start()
        forwarder = TelegramForwarder(api_id, api_hash, session_name, config_file)
        
        if not os.path.exists(download_path): os.makedirs(download_path)
        if not forwarder.load_config(): return

        await forwarder.client.start()
        logger.info("Client authentication successful")
        
        if not await forwarder.cache_target_entities():
             logger.warning("No target entities cached")
        
        source_channel_ids = [int(key) for key in forwarder.source_to_configs.keys()]
        
        forwarder.client.add_event_handler(forwarder.forward_messages, events.NewMessage(chats=source_channel_ids))
        forwarder.client.add_event_handler(forwarder.handle_message_edits, events.MessageEdited(chats=source_channel_ids))
        
        asyncio.create_task(forwarder.message_mapping_cleanup_scheduler())
        
        logger.info("Bot started successfully. Listening for new messages and edits...")
        await forwarder.client.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}"); traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
