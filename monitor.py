import sys
import os
import subprocess
import psutil
import time
from datetime import datetime, timedelta
import csv
import json
import requests
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import telebot
from telebot.formatting import escape_markdown
import traceback
from collections import defaultdict
import signal
import shutil
import argparse

# Globale Variablen
overall_total = 0
daily_totals = defaultdict(float)
last_reset_date = datetime.now()
should_stop = False
last_log_time = datetime.now()
gpu_usage_start = None
cool_down_start = None
logging_active = False

# Konfiguration speichern
def save_config():
    CONFIG['overall_total'] = overall_total
    CONFIG['daily_totals'] = dict(daily_totals)
    CONFIG['last_reset_date'] = last_reset_date.isoformat()
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'w') as config_file:
        json.dump(CONFIG, config_file, indent=4, default=str)
    
    # Create settings.json in the log directory
    settings = {
        'LOG_DIR': str(CONFIG['LOG_DIR']),
        'last_reset_date': CONFIG['last_reset_date']
    }
    settings_path = CONFIG['LOG_DIR'] / 'settings.json'
    with open(settings_path, 'w') as settings_file:
        json.dump(settings, settings_file, indent=4)

# Konfiguration aus JSON-Datei laden
def load_config():
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'r') as config_file:
        config = json.load(config_file)
    
    global overall_total, daily_totals, last_reset_date
    overall_total = config.get('overall_total', 0)
    daily_totals = defaultdict(float, config.get('daily_totals', {}))
    last_reset_date = datetime.fromisoformat(config.get('last_reset_date', datetime.now().isoformat()))
    
    return config

# Konfiguration laden
CONFIG = load_config()

# LOG_DIR als Path-Objekt erstellen
CONFIG['LOG_DIR'] = Path(CONFIG['LOG_DIR'])

# Erstellen Sie das Log-Verzeichnis, falls es nicht existiert
CONFIG['LOG_DIR'].mkdir(parents=True, exist_ok=True)

# Konfigurieren Sie das Logging
log_file = CONFIG['LOG_DIR'] / 'gpu_monitor.log'
logging.basicConfig(
    handlers=[RotatingFileHandler(log_file, maxBytes=100000, backupCount=5)],
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Telegram Bot initialisieren
bot = telebot.TeleBot(CONFIG['TELEGRAM_BOT_TOKEN'])

def send_telegram_message(message, retry_count=0):
    if not CONFIG.get('ENABLE_TELEGRAM', True):
        return
    if retry_count >= 3:
        logging.error(f"Failed to send Telegram message after 3 attempts: {message}")
        return

    try:
        escaped_message = escape_markdown(message)
        escaped_message = escaped_message.replace("*", "")
        escaped_message = escaped_message.rstrip('\\')
        bot.send_message(CONFIG['TELEGRAM_CHAT_ID'], escaped_message, parse_mode='MarkdownV2')
    except Exception as e:
        logging.error(f"Error sending Telegram message (attempt {retry_count + 1}): {str(e)}")
        time.sleep(1)
        send_telegram_message(message, retry_count + 1)

def log_error(error_msg):
    logging.error(error_msg)
    try:
        send_telegram_message(f"❌ *Error*: {error_msg}")
    except Exception as e:
        logging.error(f"Failed to send error message via Telegram: {str(e)}")

def get_gpu_usage():
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        process = subprocess.Popen(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE, 
                                   startupinfo=startupinfo)
        output, error = process.communicate()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, process.args, output, error)
        return int(output.decode('utf-8').strip())
    except subprocess.CalledProcessError as e:
        log_error(f"Fehler bei der Ausführung von nvidia-smi: {e.stderr.decode('utf-8')}")
        return None

def get_system_info():
    try:
        return {
            'cpu_usage': psutil.cpu_percent(),
            'ram_usage': psutil.virtual_memory().percent,
            'disk_usage': {disk.mountpoint: psutil.disk_usage(disk.mountpoint).percent for disk in psutil.disk_partitions()},
            'top_processes': [{'name': p.info['name'], 'cpu_percent': p.info['cpu_percent']} 
                              for p in sorted(psutil.process_iter(['name', 'cpu_percent']), key=lambda x: x.info['cpu_percent'], reverse=True)[:5]]
        }
    except Exception as e:
        log_error(f"Fehler beim Abrufen der Systeminfo: {str(e)}")
        return None

def log_to_csv(file_path, data, headers=None):
    try:
        file_exists = file_path.exists()
        with open(file_path, mode='a', newline='') as file:
            writer = csv.writer(file)
            if not file_exists and headers:
                writer.writerow(headers)
            writer.writerow(data)
    except Exception as e:
        log_error(f"Fehler beim Schreiben in CSV-Datei {file_path}: {str(e)}")

def log_regular_info(timestamp, gpu_usage, system_info):
    date_str = timestamp.strftime("%Y-%m-%d")
    log_file = CONFIG['LOG_DIR'] / f"regular_log_{date_str}.csv"
    headers = ["Timestamp", "GPU Usage", "CPU Usage", "RAM Usage", "Disk Usage", "Top Processes"]
    data = [
        timestamp,
        gpu_usage,
        system_info['cpu_usage'],
        system_info['ram_usage'],
        json.dumps(system_info['disk_usage']),
        json.dumps(system_info['top_processes'])
    ]
    log_to_csv(log_file, data, headers)

def log_gpu_usage(start_time, end_time, duration):
    global overall_total, daily_totals
    date_str = start_time.strftime("%Y-%m-%d")
    log_file = CONFIG['LOG_DIR'] / f"gpu_usage_log_{date_str}.csv"
    headers = ["Start Time", "End Time", "Duration (seconds)", "Daily Total", "Overall Total"]
    
    daily_totals[date_str] += duration
    overall_total += duration
    
    data = [start_time, end_time, duration, daily_totals[date_str], overall_total]
    log_to_csv(log_file, data, headers)
    
    message = (
        f"🧊 GPU-Nutzung unter Schwellenwert\n"
        f"Dauer: {duration:.2f}s\n"
        f"Tägliche Summe: {daily_totals[date_str]:.2f}s\n"
        f"Gesamtsumme: {overall_total:.2f}s"
    )
    send_telegram_message(message)
    
    save_config()  # Speichere die aktualisierten Werte
    
    return daily_totals[date_str], overall_total


def update_notion(start_time, end_time, duration):
    if not CONFIG.get('ENABLE_NOTION', True):
        return
    try:
        url = f"https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {CONFIG['NOTION_TOKEN']}",
            "Content-Type": "application/json",
            "Notion-Version": "2021-05-13"
        }
        data = {
            "parent": {"database_id": CONFIG['NOTION_DATABASE_ID']},
            "properties": {
                "Start Time": {"date": {"start": start_time.isoformat()}},
                "End Time": {"date": {"start": end_time.isoformat()}},
                "Duration (min)": {"number": round(duration/60, 2)},
            }
        }
        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 200:
            raise Exception(f"Notion API returned status code {response.status_code}: {response.text}")
    except Exception as e:
        log_error(f"Fehler beim Aktualisieren von Notion: {str(e)}")

def reset_total_time():
    global overall_total, last_reset_date
    overall_total = 0
    last_reset_date = datetime.now()
    CONFIG['overall_total'] = overall_total
    CONFIG['last_reset_date'] = last_reset_date.isoformat()
    save_config()
    send_telegram_message(f"🔄 *Gesamtzeit zurückgesetzt*\nNeues Startdatum: {last_reset_date.strftime('%Y-%m-%d')}")

@bot.message_handler(commands=['reset'])
def handle_reset(message):
    if str(message.chat.id) != CONFIG['TELEGRAM_CHAT_ID']:
        return
    reset_total_time()

@bot.message_handler(commands=['status'])
def handle_status(message):
    if str(message.chat.id) != CONFIG['TELEGRAM_CHAT_ID']:
        return
    status_message = (
        f"📊 *GPU-Überwachungsstatus*\n"
        f"Gesamtzeit seit {last_reset_date.strftime('%Y-%m-%d')}: *{overall_total:.2f}s*\n"
        f"Aktueller Schwellenwert: *{CONFIG['GPU_USAGE_THRESHOLD']}%*"
    )
    send_telegram_message(status_message)

def signal_handler(signum, frame):
    global should_stop
    should_stop = True
    logging.info("Erhaltenes Stoppsignal. Beende die Überwachung...")
    send_telegram_message("⚠️ *GPU-Überwachung wird beendet*")

def check_stop_file():
    if os.path.exists('stop_monitor.txt'):
        os.remove('stop_monitor.txt')
        return True
    return False

def is_script_running():
    current_process = psutil.Process()
    for process in psutil.process_iter(['name', 'cmdline']):
        if process.info['name'] == current_process.name() and \
           process.pid != current_process.pid and \
           'monitor.py' in ' '.join(process.info['cmdline']):
            return True
    return False

def main(autostart=False):
    global should_stop, last_log_time, gpu_usage_start, cool_down_start, logging_active
    
    if is_script_running():
        print("Eine Instanz des Skripts läuft bereits. Beende diesen Prozess.")
        logging.info("Versuch, eine zweite Instanz zu starten. Beende den Prozess.")
        sys.exit(0)

    # Fügen Sie hier eine kurze Verzögerung ein
    time.sleep(2)

    # Schreiben Sie die PID in eine Datei, nur wenn nicht im Autostart-Modus
    if not autostart:
        try:
            with open('gpu_monitor.pid', 'w') as f:
                f.write(str(os.getpid()))
        except PermissionError:
            logging.warning("Konnte PID-Datei nicht erstellen. Fahre trotzdem fort.")

    logging.info("GPU-Überwachung gestartet")
    send_telegram_message("🚀 *GPU-Überwachung gestartet*")

    try:
        while not should_stop:
            if check_stop_file():
                should_stop = True
                break

            current_time = datetime.now()
            current_date = current_time.strftime("%Y-%m-%d")
            
            # Überprüfe, ob ein neuer Tag begonnen hat
            if current_date not in daily_totals:
                daily_totals[current_date] = 0
            
            gpu_usage = get_gpu_usage()
            
            if gpu_usage is None:
                continue
            
            # Regelmäßiges Logging
            if (current_time - last_log_time).total_seconds() >= CONFIG['LOG_INTERVAL']:
                system_info = get_system_info()
                if system_info:
                    log_regular_info(current_time, gpu_usage, system_info)
                    last_log_time = current_time
            
            # GPU-Nutzungs-Logging
            if gpu_usage > CONFIG['GPU_USAGE_THRESHOLD']:
                if gpu_usage_start is None:
                    gpu_usage_start = current_time
                    send_telegram_message(f"🔥 *GPU-Nutzung über Schwellenwert*\nAktuell: *{gpu_usage}%*")
                    logging_active = True
                cool_down_start = None
            elif gpu_usage_start is not None:
                if cool_down_start is None:
                    cool_down_start = current_time
                elif (current_time - cool_down_start).total_seconds() >= CONFIG['COOL_DOWN_PERIOD']:
                    duration = (cool_down_start - gpu_usage_start).total_seconds()
                    log_gpu_usage(gpu_usage_start, cool_down_start, duration)
                    update_notion(gpu_usage_start, cool_down_start, duration)
                    gpu_usage_start = None
                    cool_down_start = None
                    logging_active = False
            
            # Speichere die aktuellen Werte regelmäßig
            save_config()

            time.sleep(CONFIG['CHECK_INTERVAL'])

    except Exception as e:
        error_msg = f"Unerwarteter Fehler im Hauptprogramm: {str(e)}\n{traceback.format_exc()}"
        log_error(error_msg)
        time.sleep(60)  # Warte eine Minute vor dem nächsten Versuch

    except Exception as e:
        error_msg = f"Unerwarteter Fehler im Hauptprogramm: {str(e)}"
        logging.exception(error_msg)
        send_telegram_message(f"❌ *Fehler*: {error_msg}")
    finally:
        logging.info("GPU-Überwachung beendet")
        send_telegram_message("🛑 *GPU-Überwachung wurde beendet*")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--autostart', action='store_true', help='Startet im Autostart-Modus ohne PID-Datei zu erstellen')
    args = parser.parse_args()

    # Registrieren Sie die Signalhandler
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Starte den Telegram-Bot in einem separaten Thread
    import threading
    bot_thread = threading.Thread(target=bot.polling, daemon=True)
    bot_thread.start()
    
    try:
        main(args.autostart)
    except Exception as e:
        logging.exception("Kritischer Fehler: Bot konnte nicht gestartet werden")
        send_telegram_message(f"❌ *Kritischer Fehler*: Bot konnte nicht gestartet werden\nGrund: {str(e)}")
    finally:
        # Beende den Bot-Thread sauber
        bot.stop_polling()
        bot_thread.join()
        # Entferne die PID-Datei, nur wenn sie existiert und wir nicht im Autostart-Modus sind
        if not args.autostart:
            try:
                os.remove('gpu_monitor.pid')
            except FileNotFoundError:
                pass