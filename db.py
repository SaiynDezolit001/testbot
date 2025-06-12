import json
import os

def load_films():
    if not os.path.exists('films.json'):
        return {"films": {}}
    with open('films.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def save_films(data):
    with open('films.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_film_title(code):
    data = load_films()
    return data["films"].get(str(code))

def add_film(code, title):
    data = load_films()
    data["films"][str(code)] = title
    save_films(data)

def is_code_taken(code):
    data = load_films()
    return str(code) in data["films"]

def delete_film(code):
    data = load_films()
    if str(code) in data["films"]:
        del data["films"][str(code)]
        save_films(data)
        return True
    return False
