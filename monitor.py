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
import pystray
from PIL import Image
import threading

# Globale Variablen
CONFIG = None
bot = None
last_reset_date = None
filtered_total = 0
should_stop = False
last_log_time = datetime.now()
gpu_usage_start = None
cool_down_start = None
logging_active = False

# Konfiguration speichern
def save_config():
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
    global last_reset_date
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'r') as config_file:
        config = json.load(config_file)
    
    # Handle relative and absolute paths for LOG_DIR
    log_dir = config.get('LOG_DIR', './gpu_logs')
    if log_dir.startswith('./'):
        config['LOG_DIR'] = Path(__file__).parent / log_dir[2:]
    else:
        config['LOG_DIR'] = Path(log_dir)
    
    last_reset_date = datetime.fromisoformat(config.get('last_reset_date', datetime.now().isoformat()))
    return config

def send_telegram_message(message, retry_count=0):
    if not CONFIG.get('ENABLE_TELEGRAM', False):
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
    if CONFIG.get('ENABLE_TELEGRAM', False):
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

def calculate_filtered_total():
    total = 0
    for log_file in CONFIG['LOG_DIR'].glob('gpu_usage_log_*.csv'):
        with open(log_file, 'r') as file:
            csv_reader = csv.DictReader(file)
            for row in csv_reader:
                start_time = datetime.fromisoformat(row['Start Time'])
                if start_time >= last_reset_date:
                    total += float(row['Duration (seconds)'])
    return total

def log_gpu_usage(start_time, end_time, duration):
    global filtered_total
    date_str = start_time.strftime("%Y-%m-%d")
    log_file = CONFIG['LOG_DIR'] / f"gpu_usage_log_{date_str}.csv"
    headers = ["Start Time", "End Time", "Duration (seconds)"]
    
    data = [start_time, end_time, duration]
    log_to_csv(log_file, data, headers)
    
    filtered_total = calculate_filtered_total()  # Recalculate total after logging
    
    message = (
        f"🧊 GPU-Nutzung unter Schwellenwert\n"
        f"Dauer: {duration:.2f}s\n"
        f"Gesamtsumme seit Reset: {filtered_total:.2f}s"
    )
    send_telegram_message(message)
    
    save_config()
    
    return filtered_total

def update_notion(start_time, end_time, duration):
    if not CONFIG.get('ENABLE_NOTION', False):
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
    global last_reset_date, filtered_total
    last_reset_date = datetime.now()
    filtered_total = 0
    CONFIG['last_reset_date'] = last_reset_date.isoformat()
    save_config()
    if CONFIG.get('ENABLE_TELEGRAM', False):
        send_telegram_message(f"🔄 *Gesamtzeit zurückgesetzt*\nNeues Startdatum: {last_reset_date.strftime('%Y-%m-%d')}")


# Initialize bot and set up message handlers
def initialize_bot():
    global bot
    if not CONFIG.get('ENABLE_TELEGRAM', False):
        return
    bot = telebot.TeleBot(CONFIG['TELEGRAM_BOT_TOKEN'])

    @bot.message_handler(commands=['reset'])
    def handle_reset(message):
        if str(message.chat.id) != CONFIG['TELEGRAM_CHAT_ID']:
            return
        reset_total_time()

    @bot.message_handler(commands=['status'])
    def handle_status(message):
        if str(message.chat.id) != CONFIG['TELEGRAM_CHAT_ID']:
            return
        overall_total = calculate_filtered_total()
        status_message = (
            f"📊 *GPU-Überwachungsstatus*\n"
            f"Gesamtzeit seit {last_reset_date.strftime('%Y-%m-%d')}: *{overall_total:.2f}s*\n"
            f"Aktueller Schwellenwert: *{CONFIG['GPU_USAGE_THRESHOLD']}%*"
        )
        send_telegram_message(status_message)


def signal_handler(signum, frame):
    global should_stop, icon
    should_stop = True
    logging.info("Erhaltenes Stoppsignal. Beende die Überwachung...")
    if CONFIG.get('ENABLE_TELEGRAM', False):
        send_telegram_message("⚠️ *GPU-Überwachung wird beendet*")
    if icon:
        icon.stop()

def check_stop_file():
    if os.path.exists('stop_monitor.txt'):
        os.remove('stop_monitor.txt')
        return True
    return False

def is_script_running():
    current_process = psutil.Process()
    for process in psutil.process_iter(['name', 'cmdline']):
        try:
            if process.info['name'] == current_process.name() and \
               process.pid != current_process.pid and \
               process.info['cmdline'] and \
               'monitor.py' in ' '.join(process.info['cmdline']):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def create_image(active=False):
    icon_path = Path(__file__).parent / ('tray_icon_active.png' if active else 'tray_icon.png')
    if icon_path.exists():
        return Image.open(icon_path)
    else:
        # Fallback zu einem einfachen Bild, wenn die Datei nicht existiert
        return Image.new('RGB', (64, 64), color = (240, 80, 0) if active else (0, 80, 240))

def exit_action(icon):
    global should_stop
    should_stop = True
    icon.stop()

def open_log_folder():
    log_dir = str(CONFIG['LOG_DIR'])
    try:
        if sys.platform == 'win32':
            os.startfile(log_dir)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', log_dir])
        else:
            subprocess.Popen(['xdg-open', log_dir])
    except Exception as e:
        log_error(f"Fehler beim Öffnen des Log-Ordners: {str(e)}")

def open_settings():
    config_path = Path(__file__).parent / 'config.json'
    try:
        if sys.platform == 'win32':
            os.startfile(str(config_path))
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(config_path)])
        else:
            subprocess.Popen(['xdg-open', str(config_path)])
    except Exception as e:
        log_error(f"Fehler beim Öffnen der Einstellungen: {str(e)}")


def open_dashboard():
    dashboard_path = Path(__file__).parent / 'dashboard.html'
    try:
        if sys.platform == 'win32':
            os.startfile(str(dashboard_path))
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(dashboard_path)])
        else:
            subprocess.Popen(['xdg-open', str(dashboard_path)])
    except Exception as e:
        log_error(f"Fehler beim Öffnen des Dashboards: {str(e)}")

def create_menu():
    return pystray.Menu(
        pystray.MenuItem('Dashboard', open_dashboard),
        pystray.MenuItem('Open Log Folder', open_log_folder),
        pystray.MenuItem('Settings', open_settings),
        pystray.MenuItem('Reset', reset_total_time),
        pystray.MenuItem('Exit', exit_action)
    )

def setup(icon):
    icon.visible = True

def format_duration(seconds):
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.2f}min"
    else:
        hours = seconds / 3600
        return f"{hours:.2f}h"

def update_icon_text():
    global icon, should_stop, filtered_total, logging_active
    while not should_stop:
        if icon.visible:
            gpu_usage = get_gpu_usage()
            filtered_total = calculate_filtered_total()  # Recalculate total before updating icon
            formatted_total = format_duration(filtered_total)
            icon.title = f"GPU: {gpu_usage}% | Total: {formatted_total}"
            
            # Update icon based on GPU usage
            new_icon = create_image(active=logging_active)
            icon.icon = new_icon
        time.sleep(5)

def get_status_message():
    overall_total = calculate_filtered_total()
    return (
        f"📊 *GPU-Überwachungsstatus*\n"
        f"Gesamtzeit seit {last_reset_date.strftime('%Y-%m-%d')}: *{overall_total:.2f}s*\n"
        f"Aktueller Schwellenwert: *{CONFIG['GPU_USAGE_THRESHOLD']}%*"
    )

# Erstellen Sie das Icon global
icon = pystray.Icon("GPU Monitor", create_image(), "GPU Monitor", create_menu())

def main(autostart=False):
    global should_stop, last_log_time, gpu_usage_start, cool_down_start, logging_active, icon, filtered_total, CONFIG, bot
    
    if is_script_running():
        print("Eine Instanz des Skripts läuft bereits. Beende diesen Prozess.")
        logging.info("Versuch, eine zweite Instanz zu starten. Beende den Prozess.")
        sys.exit(0)

    # Load configuration
    CONFIG = load_config()

    # Calculate filtered_total after CONFIG is loaded
    filtered_total = calculate_filtered_total()

    # Initialize bot only if Telegram is enabled
    if CONFIG.get('ENABLE_TELEGRAM', False):
        initialize_bot()

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
    if CONFIG.get('ENABLE_TELEGRAM', False):
        send_telegram_message("🚀 *GPU-Überwachung gestartet*")

    # Starte das Tray-Icon in einem separaten Thread
    icon_thread = threading.Thread(target=icon.run, args=(setup,))
    icon_thread.start()

    # Starte den Thread zur Aktualisierung des Icon-Texts
    update_thread = threading.Thread(target=update_icon_text)
    update_thread.daemon = True  # Setze den Thread als Daemon
    update_thread.start()

    # Starte den Telegram-Bot in einem separaten Thread nur wenn Telegram aktiviert ist
    if CONFIG.get('ENABLE_TELEGRAM', False):
        bot_thread = threading.Thread(target=bot.polling, daemon=True)
        bot_thread.start()

    try:
        while not should_stop:
            if check_stop_file():
                should_stop = True
                break

            current_time = datetime.now()
            current_date = current_time.strftime("%Y-%m-%d")
            
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
                    if CONFIG.get('ENABLE_TELEGRAM', False):
                        send_telegram_message(f"🔥 *GPU-Nutzung über Schwellenwert*\nAktuell: *{gpu_usage}%*")
                    logging_active = True
                    icon.icon = create_image(active=True)  # Update icon when logging starts
                cool_down_start = None
            elif gpu_usage_start is not None:
                if cool_down_start is None:
                    cool_down_start = current_time
                elif (current_time - cool_down_start).total_seconds() >= CONFIG['COOL_DOWN_PERIOD']:
                    duration = (cool_down_start - gpu_usage_start).total_seconds()
                    log_gpu_usage(gpu_usage_start, cool_down_start, duration)
                    if CONFIG.get('ENABLE_NOTION', False):
                        update_notion(gpu_usage_start, cool_down_start, duration)
                    gpu_usage_start = None
                    cool_down_start = None
                    logging_active = False
                    icon.icon = create_image(active=False)  # Update icon when logging stops
            
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
        should_stop = True
        icon.stop()
        icon_thread.join()
        # Wir müssen update_thread nicht mehr explizit beenden, da er ein Daemon-Thread ist
        logging.info("GPU-Überwachung beendet")
        if CONFIG.get('ENABLE_TELEGRAM', False):
            send_telegram_message("🛑 *GPU-Überwachung wurde beendet*")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--autostart', action='store_true', help='Startet im Autostart-Modus ohne PID-Datei zu erstellen')
    args = parser.parse_args()

    # Registrieren Sie die Signalhandler
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        main(args.autostart)
    except Exception as e:
        logging.exception("Kritischer Fehler: Bot konnte nicht gestartet werden")
        if bot:
            send_telegram_message(f"❌ *Kritischer Fehler*: Bot konnte nicht gestartet werden\nGrund: {str(e)}")
    finally:
        # Beende den Bot-Thread sauber
        if bot:
            bot.stop_polling()
        # Entferne die PID-Datei, nur wenn sie existiert und wir nicht im Autostart-Modus sind
        if not args.autostart:
            try:
                os.remove('gpu_monitor.pid')
            except FileNotFoundError:
                pass