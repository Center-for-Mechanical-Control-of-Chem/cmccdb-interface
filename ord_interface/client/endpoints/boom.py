from flask import Flask, request, jsonify

tasks = ["do this", "and this", "and this2"]

app = Flask(__name__)
@app.route('/api/dev/boom/tasks')
def add_task():
    
    new_task = request.args.get('task')
    
    
    #print("New task added: ", new_task)
    
  
    if new_task:
        tasks.append(new_task)
        return jsonify({"status": "Task added successfully", "tasks": tasks})
    else:
        return jsonify({"error": "No task provided"})

@app.route('/api/dev/boom/tasks')
def get_tasks():
    return jsonify({"message": tasks})