# GPU Monitor

This Python script monitors GPU usage and logs the data, with optional Telegram notifications and Notion integration.

It is based on NVIDIA's `nvidia-smi` command, which is a command-line utility to query and control NVIDIA GPUs.

## Installation

1. Clone this repository or download it as a ZIP archive from GitHub.

2. Ensure you have Python 3.7+ installed. You can download it from [python.org](https://www.python.org/downloads/).

3. Install the required packages:

   ```
   pip install --user -r requirements.txt
   ```

4. Adjust the `config.json` file in the same directory as `monitor.py` with your desired settings (see Configuration section below).

5. Test the script by double-clicking the `start.bat` file. To stop, use the `stop.bat` file.

6. If you want the script to start automatically at system startup:
   - Edit the `autostartMonitoring.bat` file and adjust the path to your `monitor.py` file.
   - Press `Win + R`, type `shell:startup`, and press Enter.
   - Copy the edited `autostartMonitoring.bat` file to this startup folder.

   Note: Autostart may not work reliably on all systems. For the most consistent results, it's recommended to manually start the script after system boot.

## Configuration

Edit `config.json` to customize the script's behavior:

| Key                     | Default Value                               | Description                                                                                     |
|-------------------------|---------------------------------------------|-------------------------------------------------------------------------------------------------|
| `GPU_USAGE_THRESHOLD`   | 30                                          | The threshold for GPU usage percentage to trigger notifications                                 |
| `CHECK_INTERVAL`        | 5                                           | Time in seconds between each check of GPU usage                                               |
| `COOL_DOWN_PERIOD`      | 10                                          | Time in seconds to wait after GPU usage drops below the threshold before stop measuring usage  |
| `LOG_INTERVAL`          | 600                                         | Time in seconds between logging system information (not only GPU usage)                        |
| `LOG_DIR`               | "C:\\Users\\your_username\\OneDrive\\Desktop\\gpu_logs" | Directory where log files will be stored                                                        |
| `ENABLE_TELEGRAM`       | false                                       | Flag to enable or disable Telegram notifications                                                |
| `TELEGRAM_BOT_TOKEN`    | "your_bot_token_here"                      | Token for the Telegram bot                                                                      |
| `TELEGRAM_CHAT_ID`      | "your_chat_id_here"                        | Chat ID for sending messages via Telegram                                                      |
| `ENABLE_NOTION`         | false                                      | Flag to enable or disable logging to Notion                                                    |
| `NOTION_TOKEN`          | "your_notion_token_here"                   | API token for Notion integration                                                                 |
| `NOTION_DATABASE_ID`    | "your_database_id_here"                    | Database ID for the Notion database to log data                                                |

## Testing with simGPU.py

To test the monitor, you can use `simGPU.py` to simulate GPU load:

```
python simGPU.py <target_load> <duration> [--tolerance <tolerance>]
```

Note: This requires additional packages. Install them with:

```
pip install --user torch
```

## Optional Features

### Telegram Bot

To enable Telegram notifications:

1. Create a bot using [@BotFather](https://t.me/botfather) on Telegram
2. Get your chat ID using [@userinfobot](https://t.me/userinfobot)
3. Set `ENABLE_TELEGRAM` to `true` in `config.json`
4. Add your bot token and chat ID to `config.json`

The bot supports `/reset` and `/status` commands.

### Notion Integration

To log data to a Notion database:

1. Create a Notion integration and get the API key
2. Create a database with columns: "Start Time" (Date), "End Time" (Date), "Duration (min)" (Number)
3. Share the database with your integration
4. Set `ENABLE_NOTION` to `true` in `config.json`
5. Add your Notion API key and database ID to `config.json`

## Viewing Data

You can view the raw CSV logs in the `logs` directory using Excel or a text editor. A `dashboard.html` file is also provided for data visualization.

If you have notion integration enabled, you can view the data in the Notion database.