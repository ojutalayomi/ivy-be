from flask_socketio import join_room, send
from app import socketio


@socketio.on('register')
def register(data):
    print('received message: ' + data['email'] + ' has entered the room.')
    room = data['user_status']
    join_room(room)
    send(data['email'] + ' has entered the room.', to=room)

@socketio.on('message')
def handle_message(data):
    print('received message: ' + data)

@socketio.on('error')
def handle_message(data):
    print('received error: ' + data)