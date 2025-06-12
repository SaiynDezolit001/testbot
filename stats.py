import json
import os
from datetime import datetime, timedelta

def load_stats():
    if not os.path.exists('stats.json'):
        return {"visits": []}
    with open('stats.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def save_stats(data):
    with open('stats.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def record_visit(user_id):
    data = load_stats()
    data["visits"].append({
        "user_id": user_id,
        "timestamp": datetime.now().isoformat()
    })
    save_stats(data)

def get_stats(hours=24):
    data = load_stats()
    now = datetime.now()
    cutoff = now - timedelta(hours=hours)
    
    visits = [
        visit for visit in data["visits"]
        if datetime.fromisoformat(visit["timestamp"]) > cutoff
    ]
    
    unique_users = len(set(visit["user_id"] for visit in visits))
    total_visits = len(visits)
    
    return {
        "unique_users": unique_users,
        "total_visits": total_visits
    } 