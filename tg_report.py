import requests

TOKEN = "8761095763:AAE7wfFIl4gqfnJleLbnlyYvm8gy53R_8M8"
CHAT_ID = "6803900818"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": text
    })

def send_game_start(data):
    msg = f"""
🤖 BOT FARM START

Game ID : {data.get("game_id")}
Agent   : {data.get("agent_name")}
Agent ID: {data.get("agent_id")}
"""
    send_telegram(msg)
    
def send_game_report(data):
    """
    data = dict berisi summary game
    """

    msg = f"""
🤖 BOT FARM REPORT

Game ID : {data.get('game_id')}
Agent   : {data.get('agent_name')}
Agent ID: {data.get('agent_id')}

Status  : {data.get('status')}
Result  : {data.get('result')}
Kills   : {data.get('kills')}
Deaths  : {data.get('deaths')}
Wins    : {data.get('wins')}
Losses  : {data.get('losses')}
"""

    send_telegram(msg)
