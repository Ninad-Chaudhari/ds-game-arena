from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import redis
import json
import time
import os
import urllib.parse

redis_url = os.environ.get("REDIS_URL")
parsed_url = urllib.parse.urlparse(redis_url)

r = redis.Redis(
    host=parsed_url.hostname,
    port=parsed_url.port,
    password=parsed_url.password,
    ssl=True,
    decode_responses=True
)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

QUESTIONS = [
    {"id": 1, "question": "The sky is blue.", "answer": "True"},
    {"id": 2, "question": "2 + 2 = 5", "answer": "False"},
    {"id": 3, "question": "Python is a snake.", "answer": "True"},
    {"id": 4, "question": "The Earth is flat.", "answer": "False"},
    {"id": 5, "question": "Flask is a web framework.", "answer": "True"},
]

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join_queue')
def handle_join(data):
    username = data['username']
    sid = request.sid

    current_queue = r.lrange("queue", 0, -1)
    if username not in [json.loads(p)['username'] for p in current_queue]:
        r.rpush("queue", json.dumps({"username": username, "sid": sid}))
        print(f"{username} added to queue.")

    queue_list = [json.loads(p)['username'] for p in r.lrange("queue", 0, -1)]
    socketio.emit('update_queue', queue_list)

    if r.llen("queue") >= 2:
        p1 = json.loads(r.lpop("queue"))
        p2 = json.loads(r.lpop("queue"))
        room_id = f"{p1['username']}_vs_{p2['username']}_{int(time.time())}"

        game_state = {
            "room": room_id,
            "players": {
                p1["username"]: {"answered": 0},
                p2["username"]: {"answered": 0}
            },
            "questions": QUESTIONS
        }
        r.set(room_id, json.dumps(game_state))

        socketio.emit('match_found', {'room': room_id, 'opponent': p2['username'], 'questions': QUESTIONS}, to=p1['sid'])
        socketio.emit('match_found', {'room': room_id, 'opponent': p1['username'], 'questions': QUESTIONS}, to=p2['sid'])

        queue_list = [json.loads(p)['username'] for p in r.lrange("queue", 0, -1)]
        socketio.emit('update_queue', queue_list)

@socketio.on('submit_answer')
def submit_answer(data):
    room = data['room']
    user = data['username']
    qid = data['qid']
    answer = data['answer']

    game = json.loads(r.get(room))
    correct_ans = next(q for q in game['questions'] if q['id'] == qid)['answer']
    is_correct = correct_ans.lower() == answer.lower()

    if "answers" not in game['players'][user]:
        game['players'][user]["answers"] = {}

    if str(qid) not in game['players'][user]["answers"]:
        game['players'][user]["answers"][str(qid)] = {
            "correct": is_correct
        }
        game['players'][user]["answered"] = len(game['players'][user]["answers"])

    r.set(room, json.dumps(game))

    progress = {u: v["answered"] for u, v in game['players'].items()}
    socketio.emit('progress_update', {"progress": progress}, to=room)

    all_done = all(len(p.get("answers", {})) == 5 for p in game['players'].values())
    if all_done:
        scores = {
            player: sum(1 for a in p["answers"].values() if a["correct"])
            for player, p in game['players'].items()
        }
        winner = max(scores.items(), key=lambda x: x[1])[0]
        socketio.emit('game_over', {
            "scores": scores,
            "winner": winner
        }, to=room)
        r.delete(room)

@socketio.on('join_room')
def handle_join_room(data):
    room = data['room']
    join_room(room)
    print(f"{data['username']} joined room {room}")

if __name__ == '__main__':
    socketio.run(app, debug=True)
