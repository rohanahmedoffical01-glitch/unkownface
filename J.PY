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
# Win/Loss tracking file
tracking_file = 'daily_tracking.json'
# NEW: Message mapping file for edit tracking
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
    NEW: Tracks mapping between source messages and forwarded messages for edit handling
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

class WinLossTracker:
    """
    Win/Loss tracking system for signal analysis with multi-timeframe support
    """
    
    def __init__(self, tracking_file: str):
        self.tracking_file = tracking_file
        self.tracking_data = {}
        self.load_tracking_data()
        
    def load_tracking_data(self):
        """Load tracking data from file"""
        try:
            if os.path.exists(self.tracking_file):
                with open(self.tracking_file, 'r', encoding='utf-8') as f:
                    self.tracking_data = json.load(f)
                logger.info(f"Loaded tracking data: {len(self.tracking_data)} channels")
            else:
                self.tracking_data = {}
                logger.info("No existing tracking data found")
        except Exception as e:
            logger.error(f"Error loading tracking data: {e}")
            self.tracking_data = {}
    
    def save_tracking_data(self):
        """Save tracking data to file"""
        try:
            with open(self.tracking_file, 'w', encoding='utf-8') as f:
                json.dump(self.tracking_data, f, indent=2, ensure_ascii=False)
            logger.debug("Tracking data saved successfully")
        except Exception as e:
            logger.error(f"Error saving tracking data: {e}")
    
    def is_signal_message(self, text: str) -> Optional[Dict]:
        """
        Handles any pair name with a-z, A-Z, 0-9, and hyphens.
        """
        if not text:
            return None
            
        signal_pattern = r'([a-zA-Z0-9-]+)\s*⏰\s*(\d{1,2}:\d{2})\s*.*?(\d+)\s*(?:Minutes?|Minute)\s*.*?(PUT(?:\s*DOWN)?|CALL(?:\s*UP)?)'
        match = re.search(signal_pattern, text, re.IGNORECASE | re.DOTALL)
        
        if match:
            duration_number = int(match.group(3))
            timeframe = f"M{duration_number}"
            
            return {
                'pair': match.group(1).strip(),
                'time': match.group(2).strip(),
                'duration': f"{duration_number} Minute(s)",
                'timeframe': timeframe,
                'direction': match.group(4).upper().strip(),
                'full_text': text
            }
        return None
    
    def is_result_message(self, text: str) -> Optional[Dict]:
        """
        Handles any pair name with a-z, A-Z, 0-9, and hyphens.
        """
        if not text:
            return None
            
        result_pattern = r'[📅🗓]\s*([a-zA-Z0-9-]+)\s*(Profit|Loss)\s*[✅✔️☑️](\.|)'
        match = re.search(result_pattern, text, re.IGNORECASE)
        if match:
            return {
                'pair': match.group(1),
                'result': match.group(2).lower(),
                'has_dot': bool(match.group(3)),
                'full_text': text
            }
        return None
    
    def add_signal(self, channel_id: str, signal_data: Dict):
        """Add a new signal to tracking"""
        today = datetime.now().strftime('%Y-%m-%d')
        
        if channel_id not in self.tracking_data:
            self.tracking_data[channel_id] = {}
        
        if today not in self.tracking_data[channel_id]:
            self.tracking_data[channel_id][today] = {
                'signals': [],
                'results': [],
                'stats': {'total': 0, 'wins': 0, 'losses': 0, 'percentage': 0}
            }
        
        signal_entry = {
            'pair': signal_data['pair'],
            'time': signal_data['time'],
            'timeframe': signal_data['timeframe'],
            'direction': signal_data['direction'],
            'timestamp': datetime.now().isoformat(),
            'result': None
        }
        
        self.tracking_data[channel_id][today]['signals'].append(signal_entry)
        self.save_tracking_data()
        
        logger.info(f"Added {signal_data['timeframe']} signal: {signal_data['pair']} {signal_data['direction']} at {signal_data['time']}")
    
    def add_result(self, channel_id: str, result_data: Dict):
        """
        Add result and match with existing signal from today or yesterday.
        """
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')

        if channel_id not in self.tracking_data:
            logger.warning(f"Channel {channel_id} not tracked. Ignoring result.")
            return

        dates_to_check = [d for d in [today_str, yesterday_str] if d in self.tracking_data.get(channel_id, {})]

        if not dates_to_check:
            logger.warning(f"No signals found for channel {channel_id} today or yesterday.")
            return

        matched_signal = None
        signal_date = None

        for date in dates_to_check:
            signals = self.tracking_data[channel_id][date]['signals']
            for signal in reversed(signals):
                if signal['pair'].lower() == result_data['pair'].lower() and signal['result'] is None:
                    matched_signal = signal
                    signal_date = date
                    break
            if matched_signal:
                break
        
        if matched_signal:
            if today_str not in self.tracking_data[channel_id]:
                self.tracking_data[channel_id][today_str] = {
                    'signals': [], 'results': [], 'stats': {'total': 0, 'wins': 0, 'losses': 0, 'percentage': 0}
                }

            matched_signal['result'] = result_data['result']
            result_entry = {
                'pair': result_data['pair'],
                'result': result_data['result'],
                'has_dot': result_data.get('has_dot', False),
                'timestamp': now.isoformat(),
                'signal_timestamp': matched_signal['timestamp']
            }
            
            self.tracking_data[channel_id][today_str]['results'].append(result_entry)
            
            self.update_daily_stats(channel_id, signal_date)
            if signal_date != today_str:
                 self.update_daily_stats(channel_id, today_str)

            self.save_tracking_data()
            logger.info(f"Added result: {result_data['pair']} {result_data['result']} (linked to signal from {signal_date})")
        else:
            logger.warning(f"No unmatched signal found for result: {result_data['pair']} {result_data['result']}")
    
    def update_daily_stats(self, channel_id: str, date: str):
        """Update daily statistics for a channel"""
        if channel_id not in self.tracking_data or date not in self.tracking_data[channel_id]:
            return
        
        day_data = self.tracking_data[channel_id][date]
        wins = sum(1 for r in day_data['results'] if r['result'] == 'profit')
        losses = sum(1 for r in day_data['results'] if r['result'] == 'loss')
        total = wins + losses
        percentage = round((wins / total * 100) if total > 0 else 0, 1)
        
        day_data['stats'] = {'total': total, 'wins': wins, 'losses': losses, 'percentage': percentage}
    
    def generate_results_summary_report(self, channel_id: str) -> str:
        """Generate results summary report only"""
        utc_minus_3 = pytz.timezone('Etc/GMT+3')
        today = datetime.now(utc_minus_3).strftime('%Y-%m-%d')
        
        day_data = self.tracking_data.get(channel_id, {}).get(today)
        if not day_data:
            return f"🎯 RESULTS SUMMARY for {today}:\n❌ No completed results"
        
        stats = day_data['stats']
        
        report_lines = ["🎯 RESULTS SUMMARY:"]
        if day_data['results']:
            for i, result in enumerate(day_data['results'], 1):
                time_str = datetime.fromisoformat(result['timestamp']).strftime('%H:%M')
                result_emoji = "✅" if result['result'] == 'profit' else "❌"
                dot = "." if result.get('has_dot', False) else ""
                result_text = result['result'].capitalize()  # "profit" -> "Profit", "loss" -> "Loss"
                report_lines.append(f"{i:2}. {time_str} | {result['pair']} {result_text} {result_emoji}{dot}")
        else:
            report_lines.append("   No completed results")
        
        report_lines.extend(["", "="*40, f"📊 TOTAL SIGNALS: {len(day_data['signals'])}", f"✅ COMPLETED: {len(day_data['results'])}",
                             f"👍 WINS: {stats['wins']} | 👎 LOSSES: {stats['losses']}", f"🎯 WIN RATE: {stats['percentage']}%"])
        
        return "\n".join(report_lines)
    
    def split_message(self, message: str, max_length: int = 4000) -> List[str]:
        """Split long messages into multiple parts"""
        if len(message) <= max_length:
            return [message]
        
        lines = message.split('\n')
        messages = []
        current_message = ""
        
        for line in lines:
            if len(current_message + line + '\n') > max_length:
                if current_message:
                    messages.append(current_message.rstrip())
                    current_message = line + '\n'
                else:
                    # Single line is too long, split it
                    messages.append(line[:max_length])
                    current_message = line[max_length:] + '\n'
            else:
                current_message += line + '\n'
        
        if current_message:
            messages.append(current_message.rstrip())
        
        return messages
    
    def cleanup_old_data(self):
        """Remove data older than 2 days"""
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        for channel_id in list(self.tracking_data.keys()):
            for date in list(self.tracking_data[channel_id].keys()):
                if date not in [today, yesterday]:
                    del self.tracking_data[channel_id][date]
                    logger.info(f"Cleaned up old data for {channel_id} on {date}")
        self.save_tracking_data()

class TelegramForwarder:
    
    def __init__(self, api_id: int, api_hash: str, session_name: str, config_file: str):
        self.api_id, self.api_hash, self.session_name, self.config_file = api_id, api_hash, session_name, config_file
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.config: Optional[List[Dict[str, Any]]] = None
        self.target_entities, self.source_to_configs = {}, {}
        self.tracker = WinLossTracker(tracking_file)
        # NEW: Add message tracker for edit handling
        self.message_tracker = MessageTracker()
        self.last_cleanup = datetime.now().date()
        self.last_report_time = datetime.now()
        
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

    def check_daily_cleanup(self):
        if datetime.now().date() > self.last_cleanup:
            logger.info("Performing daily cleanup")
            self.tracker.cleanup_old_data()
            self.last_cleanup = datetime.now().date()
    
    async def send_biweekly_reports(self):
        """Send reports every 2 hours with results summary only"""
        if not self.config: return
        logger.info("Executing scheduled 2-hour report task.")
        for conf in self.config:
            if conf.get("auto_biweekly_report", False) and (target_entity := self.target_entities.get(conf["target_channel_id"])):
                report = self.tracker.generate_results_summary_report(str(conf["source_channel_id"]))
                
                message_parts = self.tracker.split_message(report)
                
                try:
                    for i, part in enumerate(message_parts):
                        if len(message_parts) > 1:
                            header = f"📊 Report Part {i+1}/{len(message_parts)}\n\n"
                            await self.client.send_message(target_entity, header + part)
                        else:
                            await self.client.send_message(target_entity, part)
                        
                        if i < len(message_parts) - 1:
                            await asyncio.sleep(1)
                    
                    logger.info(f"Sent 2-hour report to {conf['target_channel_id']} in {len(message_parts)} part(s)")
                except Exception as e:
                    logger.error(f"Failed to send 2-hour report to {conf['target_channel_id']}: {e}")

    async def biweekly_report_scheduler(self):
        """Schedule reports every 2 hours"""
        while True:
            now = datetime.now()
            next_run = now.replace(minute=0, second=0, microsecond=0)
            if now.minute > 0 or now.second > 0:
                next_run += timedelta(hours=1)
            
            while next_run.hour % 2 != 0:
                next_run += timedelta(hours=1)
            
            wait_seconds = (next_run - now).total_seconds()
            logger.info(f"Scheduler: Next 2-hour report in {wait_seconds / 3600:.2f} hours at {next_run.strftime('%H:%M')}.")
            await asyncio.sleep(wait_seconds)
            await self.send_biweekly_reports()

    async def process_message_for_config(self, message, config: Dict[str, Any]) -> Optional[int]:
        """
        MODIFIED: Now returns the forwarded message ID for tracking
        """
        try:
            if not (target_entity := self.target_entities.get(config["target_channel_id"])): return None

            forward_text = None
            if message.text:
                processed_text = self.apply_text_replacements(message.text, config.get("text_to_replace", {}))
                if (src_tz := config.get("source_timezone")) and (tgt_tz := config.get("target_timezone")):
                    processed_text = self.convert_timezone(processed_text, src_tz, tgt_tz)
                forward_text = processed_text

            # Send message and capture the result
            sent_message = None

            if config.get("forward_caption_only") and message.media and forward_text:
                sent_message = await self.client.send_message(target_entity, forward_text)
            elif message.media and config.get("forward_media", True):
                if hasattr(message.media, 'document') and any(hasattr(a, 'stickerset') for a in getattr(message.media.document, 'attributes', [])):
                    if not config.get("forward_stickers", True): return None
                sent_message = await self.client.send_message(target_entity, forward_text or "", file=message.media)
            elif forward_text:
                sent_message = await self.client.send_message(target_entity, forward_text)
            
            # Return the forwarded message ID if successful
            return sent_message.id if sent_message else None
            
        except Exception as e:
            logger.error(f"Error in process_message_for_config: {e}")
            return None

    async def forward_messages(self, event):
        """
        MODIFIED: Now tracks message mappings for edit handling (only for specific channels)
        """
        message, source_id = event.message, str(event.chat_id)
        try:
            self.check_daily_cleanup()
            if not (matching_configs := self.source_to_configs.get(source_id)): return
            
            logger.info(f"Processing message from {source_id} for {len(matching_configs)} target(s)")
            
            if any(c.get("enable_winloss_tracking") for c in matching_configs) and message.text:
                if (signal_data := self.tracker.is_signal_message(message.text)):
                    self.tracker.add_signal(str(source_id), signal_data)
                if (result_data := self.tracker.is_result_message(message.text)):
                    self.tracker.add_result(str(source_id), result_data)
            
            successful_forwards = 0
            for config in matching_configs:
                # MODIFIED: Process message and get forwarded message ID
                forwarded_msg_id = await self.process_message_for_config(message, config)
                
                if forwarded_msg_id:
                    successful_forwards += 1
                    
                    # NEW: Track the message mapping for edit handling (ONLY if enabled for this channel)
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
        NEW: Handle message edits from source channels (only for channels with edit tracking enabled)
        """
        message, source_id = event.message, str(event.chat_id)
        
        try:
            logger.info(f"Message edit detected from {source_id}, message ID: {message.id}")
            
            # Get all forwarded messages for this source message
            forwarded_messages = self.message_tracker.get_forwarded_messages(source_id, message.id)
            
            if not forwarded_messages:
                logger.info(f"No forwarded messages found for edited message {source_id}:{message.id} (edit tracking may not be enabled)")
                return
            
            # Get configs for this source channel
            matching_configs = self.source_to_configs.get(source_id, [])
            if not matching_configs:
                return
            
            # Process the edited message for each forwarded instance
            successful_edits = 0
            for forwarded_info in forwarded_messages:
                target_chat_id = forwarded_info['target_chat_id']
                forwarded_msg_id = forwarded_info['forwarded_msg_id']
                
                # Find the config for this target
                target_config = None
                for config in matching_configs:
                    if str(config["target_channel_id"]) == target_chat_id:
                        target_config = config
                        break
                
                if not target_config:
                    continue
                
                # Check if edit tracking is enabled for this channel mapping
                if not target_config.get("enable_edit_tracking", False):
                    logger.info(f"Edit tracking disabled for {target_chat_id}, skipping edit")
                    continue
                
                # Get target entity
                target_entity = self.target_entities.get(target_config["target_channel_id"])
                if not target_entity:
                    continue
                
                try:
                    # Process the edited text with same transformations as original
                    edited_text = None
                    if message.text:
                        processed_text = self.apply_text_replacements(
                            message.text, 
                            target_config.get("text_to_replace", {})
                        )
                        if (src_tz := target_config.get("source_timezone")) and (tgt_tz := target_config.get("target_timezone")):
                            processed_text = self.convert_timezone(processed_text, src_tz, tgt_tz)
                        edited_text = processed_text
                    
                    # Edit the forwarded message
                    if edited_text:
                        await self.client.edit_message(
                            target_entity, 
                            forwarded_msg_id, 
                            edited_text
                        )
                        successful_edits += 1
                        logger.info(f"Successfully edited message {target_chat_id}:{forwarded_msg_id}")
                    else:
                        # If no text, try to edit with original content
                        await self.client.edit_message(
                            target_entity, 
                            forwarded_msg_id, 
                            message.text or ""
                        )
                        successful_edits += 1
                        logger.info(f"Successfully edited message {target_chat_id}:{forwarded_msg_id} (no text processing)")
                
                except Exception as e:
                    logger.error(f"Failed to edit message {target_chat_id}:{forwarded_msg_id}: {e}")
            
            logger.info(f"Successfully edited {successful_edits}/{len(forwarded_messages)} forwarded messages")
            
        except Exception as e:
            logger.error(f"An error occurred in handle_message_edits: {e}")
            traceback.print_exc()

    async def message_mapping_cleanup_scheduler(self):
        """
        NEW: Clean up old message mappings periodically
        """
        while True:
            try:
                # Clean up mappings older than 7 days every 24 hours
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
        
        # MODIFIED: Add handlers for both new messages and edits
        forwarder.client.add_event_handler(forwarder.forward_messages, events.NewMessage(chats=source_channel_ids))
        
        # NEW: Add handler for message edits
        forwarder.client.add_event_handler(forwarder.handle_message_edits, events.MessageEdited(chats=source_channel_ids))
        
        asyncio.create_task(forwarder.biweekly_report_scheduler())
        
        # NEW: Clean up old message mappings weekly
        asyncio.create_task(forwarder.message_mapping_cleanup_scheduler())
        
        logger.info("Enhanced bot started successfully. Listening for messages and edits...")
        await forwarder.client.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}"); traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())